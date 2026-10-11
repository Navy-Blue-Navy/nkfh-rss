import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


BASE_URL = "https://www.nkfh.or.jp/information/"
OUTPUT = Path(__file__).parent / "nkfh.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 3
MAX_PAGES = 100

DATE_RE = re.compile(
    r"(20\d{2})\.(\d{2})\.(\d{2})"
)


# --------------------------------------------------
# HTTP取得
# --------------------------------------------------

def fetch(url):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                f"HTTP {response.status_code} "
                f"{url}"
            )

            response.raise_for_status()

            return response

        except requests.RequestException as e:

            print(
                f"取得失敗 {attempt}/{MAX_RETRIES}:",
                e
            )

            if attempt < MAX_RETRIES:

                print(
                    "10秒待って再試行します。"
                )

                time.sleep(10)

    return None


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:

        tree = ET.parse(
            OUTPUT
        )

        for item in tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if not guid:
                continue

            old_items[guid] = {
                "title": item.findtext(
                    "title",
                    ""
                ),
                "link": item.findtext(
                    "link",
                    ""
                ),
                "description": item.findtext(
                    "description",
                    ""
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    ""
                ),
                "guid": guid,
            }

    except Exception as e:

        print(
            "既存RSS読み込みエラー:",
            e
        )

        print(
            "安全のため今回は更新しません。"
        )

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# 1ページ目取得
# --------------------------------------------------

response = fetch(
    BASE_URL
)

if response is None:

    print(
        "1ページ目を取得できないため、"
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


soup = BeautifulSoup(
    response.content,
    "html.parser"
)


# --------------------------------------------------
# 最終ページ番号取得
# --------------------------------------------------

last_page = 1

for a in soup.find_all(
    "a",
    href=True
):

    href = urljoin(
        BASE_URL,
        a["href"]
    )

    match = re.search(
        r"/information/page/(\d+)/?",
        href
    )

    if match:

        page_number = int(
            match.group(1)
        )

        last_page = max(
            last_page,
            page_number
        )


if last_page > MAX_PAGES:

    print(
        "ページ数が異常です:",
        last_page
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


print(
    "検出した最終ページ:",
    last_page
)


# --------------------------------------------------
# 記事解析
# --------------------------------------------------

def parse_page(soup):

    items = []

    blocks = soup.select(
        "div.info__block"
    )

    for block in blocks:

        link_element = block.find(
            "a",
            href=True
        )

        if link_element is None:
            continue


        link = urljoin(
            BASE_URL,
            link_element["href"]
        )


        # 病院からのお知らせの記事だけ
        if "/post_info/" not in link:
            continue


        date_element = block.select_one(
            ".info__date"
        )

        if date_element is None:
            continue


        date_text = date_element.get_text(
            " ",
            strip=True
        )


        date_match = DATE_RE.search(
            date_text
        )

        if not date_match:
            continue


        year = int(
            date_match.group(1)
        )

        month = int(
            date_match.group(2)
        )

        day = int(
            date_match.group(3)
        )


        # 掲載時刻は不明なので正午とする
        pub_dt = datetime(
            year,
            month,
            day,
            12,
            0,
            0,
            tzinfo=JST
        )


        # ------------------------------------------
        # カテゴリ
        # ------------------------------------------

        info_wrap = block.select_one(
            ".info__wrap"
        )

        category = ""

        if info_wrap is not None:

            category_text = info_wrap.get_text(
                " ",
                strip=True
            )

            category_text = DATE_RE.sub(
                "",
                category_text
            )

            category = re.sub(
                r"\s+",
                " ",
                category_text
            ).strip()


        # ------------------------------------------
        # タイトル
        #
        # aタグ全体には日付とカテゴリも入るため
        # それらを除去
        # ------------------------------------------

        title = link_element.get_text(
            " ",
            strip=True
        )

        title = DATE_RE.sub(
            "",
            title
        )

        if category:

            # 末尾のカテゴリだけ除去
            title = re.sub(
                r"\s*"
                + re.escape(category)
                + r"\s*$",
                "",
                title
            )


        title = re.sub(
            r"\s+",
            " ",
            title
        ).strip()


        if not title:
            continue


        # ------------------------------------------
        # GUID
        # ------------------------------------------

        guid = hashlib.sha256(
            (
                "nkfh|"
                + link
            ).encode("utf-8")
        ).hexdigest()


        description = ""

        if category:

            description = (
                f"カテゴリ：{category}"
            )


        items.append({
            "title": title,
            "link": link,
            "description": description,
            "pubDate": format_datetime(
                pub_dt
            ),
            "guid": guid,
        })


    return items


# --------------------------------------------------
# 全ページ取得
# --------------------------------------------------

current_items = []

page1_items = parse_page(
    soup
)

print(
    "1ページ目:",
    len(page1_items),
    "件"
)

current_items.extend(
    page1_items
)


for page in range(
    2,
    last_page + 1
):

    page_url = (
        f"https://www.nkfh.or.jp/"
        f"information/page/{page}/"
    )

    response = fetch(
        page_url
    )

    if response is None:

        print()
        print(
            f"{page}ページ目の取得に失敗しました。"
        )

        print(
            "一部欠落したRSSを作らないため、"
            "既存XMLを維持します。"
        )

        raise SystemExit(0)


    page_soup = BeautifulSoup(
        response.content,
        "html.parser"
    )


    page_items = parse_page(
        page_soup
    )


    print(
        f"{page}ページ目:",
        len(page_items),
        "件"
    )


    # 最終ページ以外が0件なら構造異常と判断
    if (
        page < last_page
        and len(page_items) == 0
    ):

        print()
        print(
            "途中ページの記事が0件です。"
        )

        print(
            "ページ構造変更等の可能性があるため、"
            "既存XMLを維持します。"
        )

        raise SystemExit(0)


    current_items.extend(
        page_items
    )


# --------------------------------------------------
# 最低限の取得結果チェック
# --------------------------------------------------

if len(current_items) < 20:

    print()
    print(
        "取得記事数が異常に少ないため、"
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 重複除去
# --------------------------------------------------

unique_items = []
seen = set()


for item in current_items:

    if item["guid"] in seen:
        continue

    seen.add(
        item["guid"]
    )

    unique_items.append(
        item
    )


current_items = unique_items


# --------------------------------------------------
# 既存RSSと統合
#
# 将来サイト側から古い記事が削除されても
# RSSには過去記事を残す
# --------------------------------------------------

all_items = []
seen_guids = set()


for item in current_items:

    all_items.append(
        item
    )

    seen_guids.add(
        item["guid"]
    )


for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        guid
    )


# --------------------------------------------------
# 日付順
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS作成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "日本鋼管福山病院 病院からのお知らせ"
)


ET.SubElement(
    channel,
    "link"
).text = BASE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "日本鋼管福山病院「病院からのお知らせ」の更新情報"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )


    ET.SubElement(
        element,
        "title"
    ).text = item["title"]


    ET.SubElement(
        element,
        "link"
    ).text = item["link"]


    ET.SubElement(
        element,
        "description"
    ).text = item["description"]


    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]


    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(
    rss
)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果表示
# --------------------------------------------------

print()
print("=" * 70)
print("RSS作成成功")
print("=" * 70)

print(
    "現在サイトから取得:",
    len(current_items),
    "件"
)

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)


print()
print("最新20件:")


for i, item in enumerate(
    all_items[:20],
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    if item["description"]:

        print(
            "    ",
            item["description"]
        )

    print(
        "    ",
        item["link"]
    )