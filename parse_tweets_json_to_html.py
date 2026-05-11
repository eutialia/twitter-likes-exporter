import datetime
import html
import json
import os
import posixpath
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from tzlocal import get_localzone

from tweet_parser import (
    MEDIA_TYPE_ANIMATED_GIF,
    MEDIA_TYPE_PHOTO,
    migrate_tweet_list,
)

DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_WORKERS = 16
OUTPUT_SUBDIRS = ("images/avatars", "images/tweets", "videos/tweets", "tweets")


def _filename_from_url(url):
    return posixpath.basename(urlparse(url).path)


class ParseTweetsJSONtoHTML():
    def __init__(self):
        self._tweets_as_json = None

        with open("config.json") as json_data_file:
            config_data = json.load(json_data_file)
            self.output_json_file_path = config_data.get('OUTPUT_JSON_FILE_PATH')

        self.output_html_directory = os.path.join(os.path.dirname(__file__), 'tweet_likes_html')

        # Per-tweet HTML files are cached. We rewrite one only when this script
        # or styles.css has changed since the file was last written.
        styles_path = os.path.join(self.output_html_directory, 'styles.css')
        self._template_mtime = max(
            os.path.getmtime(__file__),
            os.path.getmtime(styles_path) if os.path.exists(styles_path) else 0,
        )
        self._cached_tweet_files = 0
        self._written_tweet_files = 0
        self._session = requests.Session()

    def write_tweets_to_html(self):
        tweets = self.tweets_as_json
        self._ensure_output_dirs()

        tasks = self._collect_media_tasks(tweets)
        if tasks:
            print(f"Downloading {len(tasks)} new media files via {DOWNLOAD_WORKERS} workers...")
            self._download_all(tasks)

        with open(self.output_index_path, 'w', encoding='utf-8') as output_html:
            output_html.write(self._html_head('styles.css', is_index=True))
            output_html.write('<h1>Liked Tweets</h1><div class="tweet_list">')
            for tweet_data in tweets:
                output_html.write(self._render_and_save_tweet(tweet_data))
            output_html.write('</div></body></html>')

        print(
            f"Per-tweet HTML: {self._written_tweet_files} written, "
            f"{self._cached_tweet_files} reused from cache."
        )

    def _ensure_output_dirs(self):
        for sub in OUTPUT_SUBDIRS:
            os.makedirs(os.path.join(self.output_html_directory, sub), exist_ok=True)

    def _collect_media_tasks(self, tweets):
        """Walk every tweet and return (url, local_path) pairs for files we
        don't already have on disk. De-duplicated."""
        tasks = []
        seen_paths = set()

        def maybe_add(url, path):
            if not url or path in seen_paths or os.path.exists(path):
                return
            seen_paths.add(path)
            tasks.append((url, path))

        for tweet in tweets:
            maybe_add(tweet["user_avatar_url"], self._avatar_path(tweet["user_id"]))
            for item in tweet.get("tweet_media") or []:
                maybe_add(item["thumbnail_url"], self._thumb_path(item["thumbnail_url"]))
                if item.get("video_url"):
                    maybe_add(item["video_url"], self._video_path(item["video_url"]))
        return tasks

    def _download_all(self, tasks):
        succeeded = failed = 0
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
            futures = {executor.submit(self._download_one, url, path): url for url, path in tasks}
            for future in as_completed(futures):
                if future.result():
                    succeeded += 1
                else:
                    failed += 1
        if failed:
            print(f"Downloads complete: {succeeded} ok, {failed} failed.")
        else:
            print(f"Downloads complete: {succeeded} ok.")

    def _download_one(self, remote_url, local_path):
        try:
            response = self._session.get(remote_url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  failed: {remote_url} ({e})")
            return False
        with open(local_path, 'wb') as f:
            f.write(response.content)
        return True

    def _avatar_path(self, user_id):
        return os.path.join(self.output_html_directory, 'images', 'avatars', f'{user_id}.jpg')

    def _thumb_path(self, thumb_url):
        return os.path.join(self.output_html_directory, 'images', 'tweets', _filename_from_url(thumb_url))

    def _video_path(self, video_url):
        return os.path.join(self.output_html_directory, 'videos', 'tweets', _filename_from_url(video_url))

    def _render_and_save_tweet(self, tweet_data):
        tweet_html = self._render_tweet(tweet_data)
        per_tweet_path = os.path.join(
            self.output_html_directory, 'tweets', f'{tweet_data["tweet_id"]}.html'
        )
        if self._needs_per_tweet_rewrite(per_tweet_path):
            self._write_per_tweet_file(per_tweet_path, tweet_html)
            self._written_tweet_files += 1
        else:
            self._cached_tweet_files += 1
        return tweet_html

    def _render_tweet(self, tweet_data):
        output_html = '<div class="tweet_wrapper">'

        user_image_src = f'images/avatars/{tweet_data["user_id"]}.jpg'
        output_html += '<div class="tweet_author_wrapper">'
        output_html += f"<div class='tweet_author_image'><img loading='lazy' decoding='async' width='48' height='48' src='{user_image_src}'></div>"
        output_html += "<div class='author_context'>"
        output_html += f"<div class='tweet_author_name'>{self._escape(tweet_data['user_name'])}</div>"
        output_html += f"<div class='tweet_author_handle'><a href='https://www.twitter.com/{tweet_data['user_handle']}/' target='_blank'>"
        output_html += f"@{self._escape(tweet_data['user_handle'])}</a></div>"
        output_html += '</div></div>\n'

        output_html += f"<div class='tweet_content'>{self._escape(tweet_data['tweet_content'])}</div>"

        media_items = tweet_data.get("tweet_media") or []
        if media_items:
            output_html += "<div class='tweet_images_wrapper'>"
            for item in media_items:
                output_html += self._render_media_item(item)
            output_html += "</div>\n"

        parsed_datetime = datetime.datetime.strptime(
            tweet_data["tweet_created_at"], "%a %b %d %H:%M:%S %z %Y"
        ).astimezone(get_localzone())
        output_html += f"<div class='tweet_created_at'>{parsed_datetime.strftime('%a %b %d %H:%M:%S %Y')}</div>"
        output_html += "<div class='twitter_link'>"
        output_html += f"<a href='https://www.twitter.com/{tweet_data['user_handle']}/status/{tweet_data['tweet_id']}/' target='_blank'>Original tweet &#8599;</a> &#8226; "
        output_html += f"<a href='tweets/{tweet_data['tweet_id']}.html' target='_blank'>Local version</a>"
        output_html += "</div>"
        output_html += "</div>\n\n"
        return output_html

    def _render_media_item(self, item):
        thumb_rel = f"images/tweets/{_filename_from_url(item['thumbnail_url'])}"
        photo_html = (
            f"<div class='tweet_image'>"
            f"<a href='{thumb_rel}' target='_blank'>"
            f"<img loading='lazy' decoding='async' src='{thumb_rel}'>"
            f"</a></div>"
        )
        if item["type"] == MEDIA_TYPE_PHOTO or not item.get("video_url"):
            return photo_html

        video_rel = f"videos/tweets/{_filename_from_url(item['video_url'])}"
        video_full = os.path.join(self.output_html_directory, video_rel)

        # Upstream may have deleted the video (Twitter bitrot). Fall back to
        # rendering the thumbnail so the tweet isn't a broken play button.
        if not os.path.exists(video_full):
            return photo_html

        if item["type"] == MEDIA_TYPE_ANIMATED_GIF:
            video_tag = (
                f"<video autoplay loop muted playsinline preload='none' "
                f"poster='{thumb_rel}' src='{video_rel}'></video>"
            )
        else:
            video_tag = (
                f"<video controls preload='none' "
                f"poster='{thumb_rel}' src='{video_rel}'></video>"
            )
        return f"<div class='tweet_image'>{video_tag}</div>"

    def _write_per_tweet_file(self, path, body_html):
        adjusted_html = (
            body_html
            .replace("images/avatars", "../images/avatars")
            .replace("images/tweets", "../images/tweets")
            .replace("videos/tweets", "../videos/tweets")
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self._html_head('../styles.css', is_index=False))
            f.write('<div class="tweet_list">')
            f.write(adjusted_html)
            f.write('</div></body></html>')

    def _html_head(self, stylesheet_rel_path, is_index):
        parts = [
            '<html><head>',
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1.0, maximum-scale=1.0" />',
            '<title>Liked Tweets Export</title>',
            f'<link rel="stylesheet" href="{stylesheet_rel_path}"></head>',
            '<body>',
        ]
        return ''.join(parts)

    def _needs_per_tweet_rewrite(self, path):
        if not os.path.exists(path):
            return True
        return os.path.getmtime(path) < self._template_mtime

    @staticmethod
    def _escape(input_text):
        # Escape HTML special chars first, then encode non-ASCII as numeric
        # character references so output is safe regardless of file encoding.
        return html.escape(input_text).encode('ascii', 'xmlcharrefreplace').decode()

    @property
    def output_index_path(self):
        return os.path.join(self.output_html_directory, 'index.html')

    @property
    def tweets_as_json(self):
        if self._tweets_as_json is None:
            with open(self.output_json_file_path, 'rb') as json_file:
                data = json.load(json_file)
            migrated = migrate_tweet_list(data)
            if migrated:
                print(f"Migrated {migrated} tweets from legacy schema (in-memory).")
            self._tweets_as_json = data
        return self._tweets_as_json


if __name__ == "__main__":
    parser = ParseTweetsJSONtoHTML()
    print(f"Saving tweets to {parser.output_index_path}...")
    parser.write_tweets_to_html()
    print(f"Done. Output file located at {parser.output_index_path}")
