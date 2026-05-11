import datetime
import html
import json
import os
import requests
from urllib.parse import urlparse
from tzlocal import get_localzone

from tweet_parser import migrate_legacy_tweet_schema

DOWNLOAD_TIMEOUT_SECONDS = 30


class ParseTweetsJSONtoHTML():
    def __init__(self):
        self._output_html_directory = None
        self._tweets_as_json = None

        with open("config.json") as json_data_file:
            config_data = json.load(json_data_file)
            self.output_json_file_path = config_data.get('OUTPUT_JSON_FILE_PATH')

        # Per-tweet HTML files are cached. We rewrite one only when this script
        # or styles.css has changed since the file was last written.
        styles_path = os.path.join(
            os.path.dirname(__file__), 'tweet_likes_html', 'styles.css'
        )
        self._template_mtime = max(
            os.path.getmtime(__file__),
            os.path.getmtime(styles_path) if os.path.exists(styles_path) else 0,
        )
        self._cached_tweet_files = 0
        self._written_tweet_files = 0

    def write_tweets_to_html(self):
        with open(self.output_index_path, 'w', encoding='utf-8') as output_html:
            output_html.write('<html><head>')
            output_html.write('<meta charset="utf-8">')
            output_html.write('<meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1.0, maximum-scale=1.0" />')
            output_html.write('<title>Liked Tweets Export</title>')
            output_html.write('<link rel="stylesheet" href="styles.css"></head>')
            output_html.write('<body><h1>Liked Tweets</h1><div class="tweet_list">')
            for tweet_data in self.tweets_as_json:
                tweet_html = self.create_tweet_html(tweet_data)
                output_html.write(tweet_html)
            output_html.write('</div></body></html>')
        print(
            f"Per-tweet HTML: {self._written_tweet_files} written, "
            f"{self._cached_tweet_files} reused from cache."
        )

    def create_tweet_html(self, tweet_data):
        output_html = '<div class="tweet_wrapper">'

        user_image_src = f'images/avatars/{tweet_data["user_id"]}.jpg'
        full_path = f"{self.output_html_directory}/{user_image_src}"
        self.save_remote_media(tweet_data["user_avatar_url"], full_path)

        output_html += '<div class="tweet_author_wrapper">'
        output_html += f"<div class='tweet_author_image'><img loading='lazy' decoding='async' width='48' height='48' src='{user_image_src}'></div>"
        output_html += "<div class='author_context'>"
        output_html += f"<div class='tweet_author_name'>{self.parse_text_for_html(tweet_data['user_name'])}</div>"
        output_html += f"<div class='tweet_author_handle'><a href='https://www.twitter.com/{tweet_data['user_handle']}/' target='_blank'>"
        output_html += f"@{self.parse_text_for_html(tweet_data['user_handle'])}</a></div>"
        output_html += '</div></div>\n'

        output_html += f"<div class='tweet_content'>{self.parse_text_for_html(tweet_data['tweet_content'])}</div>"

        media_items = tweet_data.get("tweet_media") or []
        if media_items:
            output_html += "<div class='tweet_images_wrapper'>"
            for item in media_items:
                output_html += self.render_media_item(item)
            output_html += "</div>\n"

        parsed_datetime = datetime.datetime.strptime(
            tweet_data["tweet_created_at"], "%a %b %d %H:%M:%S %z %Y"
        ).astimezone(get_localzone())
        output_html += f"<div class='tweet_created_at'>{parsed_datetime.strftime('%a %b %d %H:%M:%S %Y')}</div>"
        output_html += "<div class='twitter_link'>"
        output_html += f"<a href='https://www.twitter.com/{tweet_data['user_handle']}/status/{tweet_data['tweet_id']}/' target='_blank'>Original tweet &#8599;</a> &#8226; "
        individual_tweet_file_path = f"{self.output_html_directory}/tweets/{tweet_data['tweet_id']}.html"
        output_html += f"<a href='tweets/{tweet_data['tweet_id']}.html' target='_blank'>Local version</a>"
        output_html += "</div>"

        output_html += "</div>\n\n"

        if self._needs_per_tweet_rewrite(individual_tweet_file_path):
            os.makedirs(os.path.dirname(individual_tweet_file_path), exist_ok=True)
            with open(individual_tweet_file_path, 'w', encoding='utf-8') as individual_tweet_file:
                individual_tweet_file.write('<html><head>')
                individual_tweet_file.write('<meta charset="utf-8">')
                individual_tweet_file.write('<meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1.0, maximum-scale=1.0" />')
                individual_tweet_file.write('<title>Liked Tweets Export</title>')
                individual_tweet_file.write('<link rel="stylesheet" href="../styles.css"></head>')
                individual_tweet_file.write('<body><div class="tweet_list">')
                adjusted_html = output_html.replace("images/avatars", "../images/avatars")
                adjusted_html = adjusted_html.replace("images/tweets", "../images/tweets")
                adjusted_html = adjusted_html.replace("videos/tweets", "../videos/tweets")
                individual_tweet_file.write(adjusted_html)
                individual_tweet_file.write('</div></body></html>')
            self._written_tweet_files += 1
        else:
            self._cached_tweet_files += 1

        return output_html

    def _needs_per_tweet_rewrite(self, path):
        if not os.path.exists(path):
            return True
        return os.path.getmtime(path) < self._template_mtime

    def render_media_item(self, item):
        thumb_name = item["thumbnail_url"].split("/")[-1]
        thumb_rel = f"images/tweets/{thumb_name}"
        thumb_full = f"{self.output_html_directory}/{thumb_rel}"
        self.save_remote_media(item["thumbnail_url"], thumb_full)

        photo_html = (
            f"<div class='tweet_image'>"
            f"<a href='{thumb_rel}' target='_blank'>"
            f"<img loading='lazy' decoding='async' src='{thumb_rel}'>"
            f"</a></div>"
        )

        if item["type"] == "photo" or not item.get("video_url"):
            return photo_html

        video_name = urlparse(item["video_url"]).path.split("/")[-1]
        video_rel = f"videos/tweets/{video_name}"
        video_full = f"{self.output_html_directory}/{video_rel}"
        self.save_remote_media(item["video_url"], video_full)

        # Upstream may have deleted the video (Twitter bitrot). Fall back to
        # rendering the thumbnail so the tweet isn't a broken play button.
        if not os.path.exists(video_full):
            return photo_html

        if item["type"] == "animated_gif":
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

    def save_remote_media(self, remote_url, local_path):
        if os.path.exists(local_path):
            return
        print(f"Downloading media {remote_url}...")
        try:
            response = requests.get(remote_url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  failed to download {remote_url}: {e}")
            return
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as handler:
            handler.write(response.content)

    def parse_text_for_html(self, input_text):
        # Escape HTML special chars first, then encode non-ASCII as numeric
        # character references so output is safe regardless of file encoding.
        return html.escape(input_text).encode('ascii', 'xmlcharrefreplace').decode()

    @property
    def output_index_path(self):
        return f'{self.output_html_directory}/index.html'

    @property
    def output_html_directory(self):
        if not self._output_html_directory:
            script_dir = os.path.dirname(__file__)
            self._output_html_directory = os.path.join(script_dir, 'tweet_likes_html')
        return self._output_html_directory

    @property
    def tweets_as_json(self):
        if not self._tweets_as_json:
            with open(self.output_json_file_path, 'rb') as json_file:
                data = json.load(json_file)
            migrated = 0
            for tweet in data:
                if "tweet_media" not in tweet and ("tweet_media_urls" in tweet or "tweet_video_urls" in tweet):
                    migrate_legacy_tweet_schema(tweet)
                    migrated += 1
            if migrated:
                print(f"Migrated {migrated} tweets from legacy schema (in-memory).")
            self._tweets_as_json = data
        return self._tweets_as_json


if __name__ == "__main__":
    parser = ParseTweetsJSONtoHTML()
    print(f"Saving tweets to {parser.output_index_path}...")
    parser.write_tweets_to_html()
    print(f"Done. Output file located at {parser.output_index_path}")
