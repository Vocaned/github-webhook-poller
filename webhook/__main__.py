import requests
import time
import sys
from dataclasses import dataclass
from collections import deque
from typing import Any
from .config import Config

@dataclass(frozen=True)
class PollResponse:
    etag: str | None
    poll_interval: int

class Webhook:
    def __init__(self, config: Config) -> None:
        self.repo_cache: dict[str, dict[str, Any]] = {}
        self.gh_headers = {
            'Authorization': f'Bearer {config.GH_TOKEN}'
        }
        self.seen_events = deque(maxlen=300)

    def poll(self, etag: str | None) -> PollResponse:
        print(f'Fetching with etag {etag}')
        eventsreq = requests.get(config.EVENT_API, headers=self.gh_headers if not etag else {**self.gh_headers, 'If-None-Match': etag})

        poll_interval = max(int(eventsreq.headers.get('X-Poll-Interval', config.POLL_INTERVAL)), config.POLL_INTERVAL)

        if eventsreq.status_code == 304:
            print('No new events.')
            return PollResponse(etag, poll_interval)

        if eventsreq.status_code not in (200, 304):
            raise Exception(f'Failed to fetch events ({eventsreq.status_code}): {eventsreq.text}')

        etag = eventsreq.headers.get('ETag', None)

        for event in eventsreq.json()[::-1]:
            if event['id'] in self.seen_events:
                continue
            self.seen_events.append(event['id']) # TODO: Should this be moved to the bottom when the webhook is actually sent, so errors will retry events

            # TODO: Refresh repo caches every once in a while
            if 'repo' in event:
                if event['repo']['id'] not in self.repo_cache:
                    reporeq = requests.get(event['repo']['url'], headers=self.gh_headers)
                    if reporeq.status_code != 200:
                        raise Exception(f'Failed to fetch repo at {event["repo"]["url"]} ({reporeq.status_code}): {reporeq.text}')
                    repo = reporeq.json()
                    self.repo_cache[event['repo']['id']] = repo
                    event['repo'] = repo
                else:
                    event['repo'] = self.repo_cache[event['repo']['id']]

                if event['repo']['full_name'] in config.REPO_BLACKLIST:
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

            if event_type in config.EVENT_BLACKLIST:
                print('Blacklisted event type', event_type)
                continue

            if config.USER_WHITELIST:
                if event['actor']['login'] not in config.USER_WHITELIST:
                    print('Unwhitelisted user login', event['actor']['login'])
                    continue

            data = {
                **event['payload'],
                'repository': event['repo'],
                'sender': event['actor']
            }

            if event_type in ('pull_request', 'pull_request_review', 'pull_request_review_comment'):
                prreq = requests.get(event['payload']['pull_request']['url'], headers=self.gh_headers)
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
                # TODO: Do we need to check if the repo exists in the cache (probably not since it'll be brand new)
                # TODO: Should repo fetching be turned into a separate function as it's done above as well
                reporeq = requests.get(event['repo']['url'], headers=self.gh_headers)
                if reporeq.status_code != 200:
                    raise Exception(f'Failed to fetch repo at {event["repo"]["url"]} ({reporeq.status_code}): {reporeq.text}')
                repo = reporeq.json()['parent']

            if event_type == 'push':
                commitsreq = requests.get(f"https://api.github.com/repos/{event['repo']['full_name']}/compare/{event['payload']['before']}...{event['payload']['head']}", headers=self.gh_headers)
                if commitsreq.status_code != 200:
                    raise Exception(f'Failed to fetch commit compare at https://api.github.com/repos/{event["repo"]["full_name"]}/compare/{event["payload"]["before"]}...{event["payload"]["head"]} ({commitsreq.status_code}): {commitsreq.text}')
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
                    'forced': commits['status'] == 'diverged', # are there situations where branches diverge outside of force pushing?
                    'head_commit': commitlist[0] if commitlist else None, # is this correct?
                    'pusher': {
                        'name': event['actor']['display_login'],
                        'username': event['actor']['login']
                    },
                    'repository': event['repo'],
                    'sender': event['actor']
                }

            # TODO: should this be moved into the loop in __main__, rather than in the gh api class
            webhook_headers = {
                'X-GitHub-Event': event_type,
                'User-Agent': 'GitHub-Hookshot/totallyrealwebhook',
            }

            r = requests.post(config.DISCORD_WEBHOOK, json=data, headers=webhook_headers)
            print(f'Sent {event_type} -> {r.status_code}: {r.text}')

        return PollResponse(etag, poll_interval)

if __name__ == '__main__':
    config = Config.from_toml('config.toml')
    webhook = Webhook(config)

    # TODO: Right now events that happened while the bot was down might be resent. Do we want this,
    # or should we lose events while bot is down, or do we store the events already seen and process the rest?
    etag = None
    while True:
        pollresponse = webhook.poll(etag)
        etag = pollresponse.etag
        # This is going to sleep for longer than the specified poll_interval, as sending the webhooks to discord already took some time not accounted for.
        # For our purposes this doesn't really matter
        print('Sleeping for', pollresponse.poll_interval)
        time.sleep(pollresponse.poll_interval)

