import json
import os
import random
import time

import requests

from tweet_parser import TweetParser, migrate_tweet_list

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_DELAY_MIN = 1.0
DEFAULT_DELAY_MAX = 15.0
DELAY_PEAK_RATIO = 0.15  # mode of triangular dist inside [min, max]


class TweetDownloader():

    def __init__(self):
        with open("config.json") as json_data_file:
            config_data = json.load(json_data_file)
            self.twitter_user_id = config_data.get('USER_ID')
            self.header_authorization = config_data.get('HEADER_AUTHORIZATION')
            self.header_cookie = config_data.get('HEADER_COOKIES')
            self.header_csrf = config_data.get('HEADER_CSRF')
            self.output_json_file_path = config_data.get('OUTPUT_JSON_FILE_PATH')
            self.delay_min = float(config_data.get('REQUEST_DELAY_MIN', DEFAULT_DELAY_MIN))
            self.delay_max = float(config_data.get('REQUEST_DELAY_MAX', DEFAULT_DELAY_MAX))
            self.force_refetch = bool(config_data.get('FORCE_FULL_REFETCH', False))

        lo, hi = sorted((max(self.delay_min, 0.0), max(self.delay_max, 0.0)))
        self._delay_lo = lo
        self._delay_hi = hi
        self._delay_peak = lo + DELAY_PEAK_RATIO * (hi - lo)

    def retrieve_all_likes(self):
        existing_tweets = [] if self.force_refetch else self._load_existing_tweets()
        existing_ids = {t["tweet_id"] for t in existing_tweets}
        if existing_tweets:
            print(f"Loaded {len(existing_tweets)} previously-fetched tweets; will stop at first known ID.")
        elif self.force_refetch:
            print("FORCE_FULL_REFETCH set — ignoring existing data.")

        new_tweets = []
        likes_page = self.retrieve_likes_page()
        page_cursor = self.get_cursor(likes_page)
        old_page_cursor = None
        current_page = 1
        reached_known = False

        while likes_page and page_cursor and page_cursor != old_page_cursor and not reached_known:
            print(
                f"Fetching likes page: {current_page} "
                f"(collected {len(new_tweets)} new tweets so far)"
            )
            current_page += 1
            for raw_tweet in likes_page:
                parser = TweetParser.from_raw_entry(raw_tweet)
                if parser is None:
                    continue
                try:
                    tid = parser.tweet_id
                except KeyError:
                    continue
                if tid in existing_ids:
                    print(f"  reached previously-fetched tweet {tid}; stopping pagination.")
                    reached_known = True
                    break
                try:
                    new_tweets.append(parser.tweet_as_json())
                    existing_ids.add(tid)
                except KeyError:
                    print(
                        f"KeyError while parsing tweet: "
                        f"https://x.com/{parser.user_handle}/status/{tid}"
                    )
                    continue
            if reached_known:
                break
            old_page_cursor = page_cursor
            self._sleep_before_next_request()
            likes_page = self.retrieve_likes_page(cursor=page_cursor)
            page_cursor = self.get_cursor(likes_page)

        combined = new_tweets + existing_tweets
        with open(self.output_json_file_path, 'w') as f:
            json.dump(combined, f)
        print(
            f"Saved {len(combined)} total tweets "
            f"({len(new_tweets)} newly fetched, {len(existing_tweets)} preserved)."
        )

    def _load_existing_tweets(self):
        if not self.output_json_file_path or not os.path.exists(self.output_json_file_path):
            return []
        try:
            with open(self.output_json_file_path, 'rb') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not load existing tweets ({e}); starting fresh.")
            return []
        if not isinstance(data, list):
            return []
        migrated = migrate_tweet_list(data)
        if migrated:
            print(f"Migrated {migrated} tweets from legacy schema in memory.")
        return data

    def retrieve_likes_page(self, cursor=None):
        likes_url = 'https://api.twitter.com/graphql/QK8AVO3RpcnbLPKXLAiVog/Likes'
        variables_data_encoded = json.dumps(self.likes_request_variables_data(cursor=cursor))
        features_data_encoded = json.dumps(self.likes_request_features_data())
        response = requests.get(
            likes_url,
            params={"variables": variables_data_encoded, "features": features_data_encoded},
            headers=self.likes_request_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return self.extract_likes_entries(response.json())

    def extract_likes_entries(self, raw_data):
        return raw_data['data']['user']['result']['timeline_v2']['timeline']['instructions'][0]['entries']

    def get_cursor(self, page_json):
        if not page_json:
            return None
        return page_json[-1].get('content', {}).get('value')

    def _sleep_before_next_request(self):
        if self._delay_hi <= 0:
            return
        # Triangular biased toward the short end: behaves like a fast scroll
        # most of the time with the occasional longer pause.
        delay = random.triangular(self._delay_lo, self._delay_hi, self._delay_peak)
        print(f"  sleeping {delay:.1f}s before next page request...")
        time.sleep(delay)

    def likes_request_variables_data(self, cursor=None):
        variables_data = {
            "userId": self.twitter_user_id,
            "count": 100,
            "includePromotedContent": False,
            "withSuperFollowsUserFields": False,
            "withDownvotePerspective": False,
            "withReactionsMetadata": False,
            "withReactionsPerspective": False,
            "withSuperFollowsTweetFields": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": False,
            "withV2Timeline": True
        }
        if cursor:
            variables_data["cursor"] = cursor
        return variables_data

    def likes_request_headers(self):
        return {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Authorization': self.header_authorization,
            'Accept-Language': 'en-US,en;q=0.9',
            'Host': 'api.twitter.com',
            'Origin': 'https://twitter.com',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
            'Referer': 'https://twitter.com/',
            'Connection': 'keep-alive',
            'Cookie': self.header_cookie,
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
            'x-csrf-token': self.header_csrf,
            'x-twitter-auth-type': 'OAuth2Session'
        }

    def likes_request_features_data(self):
        return {
            "responsive_web_twitter_blue_verified_badge_is_enabled": True,
            "verified_phone_label_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "view_counts_public_visibility_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": False,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_uc_gql_enabled": True,
            "vibe_api_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
            "interactive_text_enabled": True,
            "responsive_web_text_conversations_enabled": False,
            "responsive_web_enhance_cards_enabled": False
        }

if __name__ == '__main__':
    downloader = TweetDownloader()
    print(f'Starting retrieval of likes for Twitter user {downloader.twitter_user_id}...')
    downloader.retrieve_all_likes()
    print(f'Done. Likes JSON saved to: {downloader.output_json_file_path}')
