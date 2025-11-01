import requests
import tomllib
import time
import sys
from datetime import datetime, timezone

with open('config.toml', 'rb') as f:
    config = tomllib.load(f)

gh_headers = {
    'Authorization': f'Bearer {config["GH_TOKEN"]}'
}

repo_cache = {}

# Skip events that happened before script was ran
latest_event: datetime = datetime.now(tz=timezone.utc)
poll_interval = 5*60
etag = None

while True:
    print(f'Fetching with etag {etag}')
    eventsreq = requests.get('https://api.github.com/orgs/discord/events', headers=gh_headers if not etag else {**gh_headers, 'If-None-Match': etag})
    print('Status', eventsreq.status_code)

    poll_interval = max(int(eventsreq.headers.get('X-Poll-Interval', 5*60)), 5*60)

    if eventsreq.status_code == 304:
        print('No new events, sleeping for', poll_interval)
        time.sleep(poll_interval)
        continue

    if eventsreq.status_code not in (200, 304):
        print(eventsreq.text)
        sys.exit(1)

    etag = eventsreq.headers.get('ETag', None)
    new_latest_event = None

    for event in eventsreq.json()[::-1]:
        # TODO: do we have to track seen event IDs?
        date = datetime.fromisoformat(event['created_at'])
        if date <= latest_event:
            print('Skipping event at', date)
            continue

        if not new_latest_event or date > new_latest_event:
            new_latest_event = date

        # TODO: Refresh repo caches every once in a while
        if 'repo' in event:
            if event['repo']['id'] not in repo_cache:
                reporeq = requests.get(event['repo']['url'], headers=gh_headers)
                if reporeq.status_code != 200:
                    print(reporeq.text)
                    # TODO: error handling
                    sys.exit(1)
                repo = reporeq.json()
                repo_cache[event['repo']['id']] = repo
                event['repo'] = repo
            else:
                event['repo'] = repo_cache[event['repo']['id']]

            if event['repo']['full_name'] in config['REPO_BLACKLIST']:
                print('Skipping blacklisted repo', event['repo']['full_name'])
                continue

        # Really we should be fetching the user object here
        # However, the only new property Discord needs is html_url, which can be derived from the partial user
        event['actor']['html_url'] = event['actor']['url'].replace('api.github.com/users', 'github.com')

        EVENT_TYPES = {
            'CommitCommentEvent': 'commit_comment',
            'CreateEvent': 'create',
            'DeleteEvent': 'delete',
            'DiscussionEvent': 'discussion',
            ...: 'discussion_comment', # Where will I get this data
            'ForkEvent': 'fork', # Wrong repo shown in Discord, github api doesn't show origin repo details
            # 'GollumEvent': 'gollum', # Not implemented by Discord
            'IssueCommentEvent': 'issue_comment',
            'IssuesEvent': 'issues',
            'MemberEvent': 'member',
            'PublicEvent': 'public',
            'PullRequestEvent': 'pull_request',
            'PullRequestReviewEvent': 'pull_request_review',
            'PullRequestReviewCommentEvent': 'pull_request_review_comment',
            'PushEvent': 'push',
            'ReleaseEvent': 'release',
            'WatchEvent': 'watch'
        }

        event_type = EVENT_TYPES.get(event['type'], None)

        if not event_type:
            print('Unhandled event type', event['type'])
            continue

        if event_type in config['EVENT_BLACKLIST']:
            print('Blacklisted event type', event_type)
            continue

        data = {
            **event['payload'],
            'repository': event['repo'],
            'sender': event['actor']
        }

        if event_type in ('pull_request', 'pull_request_review', 'pull_request_review_comment'):
            prreq = requests.get(event['payload']['pull_request']['url'], headers=gh_headers)
            if prreq.status_code != 200:
                print(event['payload']['pull_request']['url'])
                print(prreq.text)
                sys.exit(1)
            data['pull_request'] = prreq.json()

        if event_type == 'pull_request_review':
            actionmap = {
                'created': 'submitted',
                'updated': 'edited',
                'dismissed': 'dismissed'
            }
            data['action'] = actionmap.get(event['payload']['action'], 'submitted')

        if event_type == 'fork':
            reporeq = requests.get(event['repo']['url'], headers=gh_headers)
            if reporeq.status_code != 200:
                print(reporeq.text)
                # TODO: error handling
                sys.exit(1)
            repo = reporeq.json()['parent']

        if event_type == 'push':
            commitsreq = requests.get(f"https://api.github.com/repos/{event['repo']['full_name']}/compare/{event['payload']['before']}...{event['payload']['head']}", headers=gh_headers)
            if commitsreq.status_code != 200:
                print(f"https://api.github.com/repos/{event['repo']['full_name']}/compare/{event['payload']['before']}...{event['payload']['head']}")
                print(commitsreq.text)
                sys.exit(1)
            commits = commitsreq.json()
            commitlist = [{'id': c['commit']['tree']['sha'], **c['commit'], 'url': c['html_url']} for c in commits['commits']]

            data = {
                'after': event['payload']['head'],
                'base_ref': event['payload']['before'], # is this correct?
                'ref': event['payload']['ref'],
                'before': event['payload']['before'],
                'commits': commitlist,
                'compare': f'https://github.com/{event['repo']['full_name']}/compare/{event['payload']['before']}...{event['payload']['head']}',
                'created': False, # where to find this?
                'deleted': False, # where to find this?
                'forced': False, # This could be derived from `commits['status'] == 'diverged'`, however discord doesn't show commit details on force pushes, so for now it's always disabled.
                'head_commit': commitlist[0], # is this correct?
                'pusher': {
                    'name': event['actor']['display_login'],
                    'username': event['actor']['login']
                },
                'repository': event['repo'],
                'sender': event['actor']
            }

        webhook_headers = {
            'X-GitHub-Event': event_type,
            'User-Agent': 'GitHub-Hookshot/totallyrealwebhook',
        }

        r = requests.post(config['DISCORD_WEBHOOK'], json=data, headers=webhook_headers)
        print(f'Sent {event_type} -> {r.status_code}: {r.text}')

    if new_latest_event and new_latest_event > latest_event:
        latest_event = new_latest_event

    # This is going to sleep for longer than the specified poll_interval, as sending the webhooks to discord already took some time not accounted for.
    # For our purposes this doesn't really matter
    print('Sleeping for', poll_interval)
    time.sleep(poll_interval)
