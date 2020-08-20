import os
import re
import json
import time
import logging
from operator import itemgetter
from functools import lru_cache
import requests
import pandas as pd
import arxiv
import tweepy
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from s3_memoize import s3_fifo_cache, s3_lru_cache

#logging.basicConfig(level=logging.DEBUG)
logging.basicConfig(level=logging.ERROR)


app = App(
    process_before_response=False
)

def get_twitter_api():
    if os.getenv('TWITTER_API_KEY') and os.getenv('TWITTER_API_SECRET_KEY'):
        auth = tweepy.AppAuthHandler(os.environ['TWITTER_API_KEY'], os.environ['TWITTER_API_SECRET_KEY'])
        return tweepy.API(auth, wait_on_rate_limit=True, wait_on_rate_limit_notify=True)
    else:
        return None

twitter_api = get_twitter_api()


def is_retry_request(request):
    h = request.headers
    return h.get('x-slack-retry-num') and h.get('x-slack-retry-reason') and h.get('x-slack-retry-reason')[0] == 'http_timeout'

def is_user(e):
    return e.get('user') and e.get('bot_id') is None

def get_arxiv_id(text):
    m = re.search(r'https?://arxiv\.org/(abs|pdf)/([0-9]+\.[0-9v]+)(\.pdf)?', text)
    return m.group(2) if m and m.group(2) else None

def find_all_unique_arxiv_ids(text):
    m = re.findall(r'https?://arxiv\.org/(abs|pdf)/([0-9]+\.[0-9v]+)(\.pdf)?', text)
    return list(set([get_arxiv_id_no_v(item[1]) for item in m])) if m else []

def get_arxiv_id_no_v(arxiv_id):
    return re.sub(r'v[0-9]+$', r'', arxiv_id)

# @lru_cache(maxsize=128)
@s3_fifo_cache(maxsize=128, bucket_name='arxivapp-tweeted-arxiv-id-counts')
def get_tweeted_arxiv_id_counts(q):
    start = time.time()
    i = 0
    arxiv_ids = []
    try:
        # https://developer.twitter.com/en/docs/basics/rate-limits
        for status in tweepy.Cursor(twitter_api.search, q=q, count=100, result_type='recent', tweet_mode='extended').items(100*400):
            ids = find_all_unique_arxiv_ids(str(status._json)) # TODO: _json is a private member
            arxiv_ids.extend(ids)
            print(i) if i % 100 == 0 else None
            i += 1
    except Exception as e:
        print('Exception: {}'.format(str(e)))
    df = pd.DataFrame(arxiv_ids, columns=['arxiv_id'])
    counts = df['arxiv_id'].value_counts()
    print(len(df), len(counts))
    print('get_tweeted_arxiv_id_counts: {:.6f} sec'.format(time.time() - start))
    return counts.to_json()

# @lru_cache(maxsize=128)
@s3_fifo_cache(maxsize=128, bucket_name='arxivapp-arxiv-query')
def arxiv_query(id_list_str='', q='', max_chunk_id_list=200): # list is unhashable, so it needs to convert from list to string to enable lru_cache
    start = time.time()
    id_list = json.loads(id_list_str)
    rs = []
    cdr = id_list
    try:
        for i in range(1+len(id_list)//max_chunk_id_list): # avoid "HTTP Error 414 in query" (URI Too Long)
            car = cdr[:max_chunk_id_list]
            cdr = cdr[max_chunk_id_list:]
            print(len(car), len(''.join(car)))
            r = arxiv.query(id_list=car, query=q) # this will automatically sleep
            rs.extend(r)
    except Exception as e:
        print('Exception: {}'.format(str(e)))
    print('arxiv_query: {:.6f} sec'.format(time.time() - start))
    return json.dumps(rs)

def is_valid_slack_user_id(user_id):
    # https://github.com/slackapi/slack-api-specs/blob/master/web-api/slack_web_openapi_v2.json
    # "defs_user_id": { "pattern": "^[UW][A-Z0-9]{2,}$", ... }
    return re.match(r'^[UW][A-Z0-9]{2,10}$', user_id) # TODO: upper limit seems like 10 but not sure

def get_deepl_auth_key(user_id):
    if is_valid_slack_user_id(user_id) and os.getenv('DEEPL_AUTH_KEY_{}'.format(user_id)):
        # print('Found a user specific deepl auth key: {}'.format(user_id))
        return os.getenv('DEEPL_AUTH_KEY_{}'.format(user_id)) # user specific auth key
    else:
        return os.getenv('DEEPL_AUTH_KEY') # default auth key
        # return None # or just reject

# @lru_cache(maxsize=128)
@s3_lru_cache(maxsize=128, bucket_name='arxivapp-translate-text')
def translate_text(text, target_lang='JA'): # drop user_id to increase cache hits rate
    global user_id # set user_id global for effective lru_cache. see handle_message.
    deepl_auth_key = get_deepl_auth_key(user_id)
    if deepl_auth_key:
        return translate_deepl_api(text, deepl_auth_key, target_lang=target_lang)
    else:
        # return translator.translate_another_api(text, target_lang=target_lang) # for another translation api
        return None

def translate_deepl_api(text, auth_key, target_lang='JA'):
    # https://www.deepl.com/docs-api/translating-text/
    start = time.time()
    params = {
        'auth_key': auth_key,
        'text': text,
        'target_lang': target_lang
    }
    r = requests.post('https://api.deepl.com/v2/translate', data=params)
    if r.status_code == requests.codes.ok:
        j = r.json()
        print('translate_deepl_api: {:.6f} sec'.format(time.time() - start))
        return j['translations'][0]['text'] if 'translations' in j else None # TODO: need more check?
    else:
        print('Failed to translate: {}'.format(r.text))
        return None

def generate_response(r):
    arxiv_id = get_arxiv_id(r['id'])
    arxiv_id_no_v = get_arxiv_id_no_v(arxiv_id)
    vanity_url = 'https://www.arxiv-vanity.com/papers/{}/'.format(arxiv_id_no_v)
    tweets_url = 'https://twitter.com/search?q=arxiv.org%2Fabs%2F{}%20OR%20arxiv.org%2Fpdf%2F{}.pdf%20&f=live'.format(arxiv_id_no_v, arxiv_id_no_v)
    tags = ' | '.join(['{}'.format(t['term']) for t in r['tags']])
    u = r['updated_parsed']
    p = r['published_parsed']
    # date = '{:04d}/{:02d}/{:02d}, {:04d}/{:02d}/{:02d}'.format(p.tm_year, p.tm_mon, p.tm_mday, u.tm_year, u.tm_mon, u.tm_mday)
    date = '{:04d}/{:02d}/{:02d}, {:04d}/{:02d}/{:02d}'.format(p[0], p[1], p[2], u[0], u[1], u[2])
    comment = r['arxiv_comment'] or ''
    vanity = '<{}|vanity>'.format(vanity_url)
    tweets = '<{}|{} tweets>'.format(tweets_url, r['num_tweets'] if 'num_tweets' in r else '?')
    summary = re.sub(r'\n', r' ', r['summary'])
    translation = translate_text(summary)
    summary = translation if translation and len(translation) > 0 else summary
    # summary = '\n'.join([translation, summary])
    lines = [
        r['id'],
        re.sub(r'\n', r' ', r['title']),
        ', '.join(r['authors']),
        ', '.join([date, vanity, tweets, tags, comment]),
        summary
    ]
    return '\n'.join(lines)

@app.message(re.compile(r'.*https?://arxiv\.org/(abs|pdf)/([0-9]+\.[0-9v]+)(\.pdf)?.*'))
def handle_arxiv_url(payload, say, logger, ack, request):
    if is_retry_request(request):
        # Slack Events API needs to respond "200 OK" within 3 seconds.
        # if it came here, previous request should not be handled properly.
        print('Retry event request')
        # return
    e = payload['event']
    if not is_user(e):
        print('Bot message: ignored')
        return
    ack({'text': 'arXiv URL Found.', 'thread_ts': e['ts']})
    arxiv_id = get_arxiv_id(e['text']) # arxiv_id was already checked so it should not be None
    rs = json.loads(arxiv_query(id_list_str=json.dumps([arxiv_id])))
    text = arxiv_id
    if rs and len(rs) > 0:
        r = rs[0]
        arxiv_id_no_v = get_arxiv_id_no_v(arxiv_id)
        arxiv_id_counts = json.loads(get_tweeted_arxiv_id_counts('"arxiv.org/abs/{}" OR "arxiv.org/pdf/{}.pdf"'.format(arxiv_id_no_v, arxiv_id_no_v)))
        r['arxiv_id_no_v'] = arxiv_id_no_v
        r['num_tweets'] = arxiv_id_counts[arxiv_id_no_v] if arxiv_id_no_v in arxiv_id_counts else 0
        global user_id # set user_id global for effective lru_cache. see translate_text.
        user_id = e['user']
        text = generate_response(r) # generate_response(r, user_id)
    else:
        text = 'No result found: {}'.format(arxiv_id)
    say({'text': text, 'thread_ts': e['ts']})

def get_top5_arg(text):
    m = re.search(r'^top5(\s.+)?$', text)
    return m.group(1).translate(str.maketrans({'“': '"', '”': '"'})) if m and m.group(1) else None

def is_valid_top5_arg(text):
    return re.match(r'[\s\w":\.]+', text)

@app.message(re.compile(r'^top5(\s.+)?$'))
def handle_top5(payload, say, logger, ack, request):
    if is_retry_request(request):
        # Slack Events API needs to respond "200 OK" within 3 seconds.
        # if it came here, previous request should not be handled properly.
        print('Retry event request')
        # return
    e = payload['event']
    if not is_user(e):
        print('Bot message: ignored')
        return
    ack({'text': 'Processing top5 message.', 'thread_ts': e['ts']})
    arg = get_top5_arg(e['text'])
    if arg and not is_valid_top5_arg(arg):
        text = 'Invalid argument'
        print(arg)
        say({'text': text, 'thread_ts': e['ts']})
        return
    max_results = 5
    arxiv_id_counts = json.loads(get_tweeted_arxiv_id_counts('"arxiv.org"'))
    if arxiv_id_counts is None or len(arxiv_id_counts) < 1:
        text = 'No twitter result found'
        say({'text': text, 'thread_ts': e['ts']})
        return
    id_list = sorted(list(arxiv_id_counts.keys()))
    q = 'cat:cs.CV OR cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.NE OR cat:stat.ML'
    q = arg if arg else q
    print(q)
    rs = json.loads(arxiv_query(id_list_str=json.dumps(id_list), q=q, max_chunk_id_list=200))
    print(len(id_list), len(rs))
    if len(rs) < 1:
        text = 'No arXiv result found'
        say({'text': text, 'thread_ts': e['ts']})
        return
    i = 0
    for r in rs:
        arxiv_id = get_arxiv_id(r['id'])
        arxiv_id_no_v = get_arxiv_id_no_v(arxiv_id)
        r['arxiv_id_no_v'] = arxiv_id_no_v
        r['num_tweets'] = arxiv_id_counts[arxiv_id_no_v] if arxiv_id_no_v in arxiv_id_counts else 0
        print(i, r['arxiv_id_no_v'], r['num_tweets']) if r['num_tweets'] == 0 else None
        i += 1
    rs.sort(key=itemgetter('num_tweets'), reverse=True)
    rs = rs[:max_results]
    global user_id # set user_id global for effective lru_cache. see translate_text.
    user_id = e['user']
    for r in rs:
        text = generate_response(r)
        say({'text': text, 'thread_ts': e['ts']})


flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

@flask_app.route('/')
def hello():
    return 'hello'

@flask_app.route('/slack/events', methods=['POST'])
def slack_events():
    return handler.handle(request)


# pip install -r requirements.txt
# export SLACK_SIGNING_SECRET=***
# export SLACK_BOT_TOKEN=xoxb-***
# FLASK_APP=app.py FLASK_ENV=development flask run -p 3000
