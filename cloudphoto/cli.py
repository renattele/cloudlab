"""cloudphoto — управление фотоархивом в Yandex Object Storage."""

import argparse
import html
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# https://yandex.cloud/ru/docs/storage/tools/boto
ENDPOINT = "https://storage.yandexcloud.net"
REGION = "ru-central1"
ENV_VARS = ("BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")

# Схема хранилища (см. README):
#   photos/<альбом>/          — пустой объект-маркер, альбом существует, пока он есть
#   photos/<альбом>/<имя>     — фотография с исходным именем файла <имя>
#   index.html, error.html, album{N}.html — страницы сайта в корне бакета
PHOTOS = "photos/"
PHOTO_SUFFIXES = (".jpg", ".jpeg")


class Error(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Error("Ошибка в аргументах")


def parse_args(argv):
    parser = Parser(prog="cloudphoto")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("list").add_argument("--album")
    for name in ("upload", "download"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--album", required=True)
        cmd.add_argument("--path", default=".")
    cmd = commands.add_parser("delete")
    cmd.add_argument("--album", required=True)
    cmd.add_argument("--photo")
    commands.add_parser("mksite")
    args = parser.parse_args(argv)

    # Имя альбома становится сегментом ключа и URL: "/" сломает иерархию, "." и ".." — пути.
    album = getattr(args, "album", None)
    if album is not None and (album in ("", ".", "..") or "/" in album):
        parser.error("album")
    photo = getattr(args, "photo", None)
    if photo is not None and (photo == "" or "/" in photo):
        parser.error("photo")
    return args


def album_prefix(album):
    return f"{PHOTOS}{album}/"


class Archive:
    def __init__(self, bucket):
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name=REGION,
            # В имени бакета-сайта есть точки: virtual-hosted style ломает проверку TLS.
            config=Config(s3={"addressing_style": "path"}),
        )

    def _list(self, prefix, delimiter="/"):
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix, Delimiter=delimiter
        )
        for page in pages:
            yield from page.get("CommonPrefixes", [])
            yield from page.get("Contents", [])

    def albums(self):
        # str в Python сравнивается по кодовым точкам — это тот же порядок, что и байты UTF-8.
        return sorted(p["Prefix"][len(PHOTOS):-1] for p in self._list(PHOTOS) if "Prefix" in p)

    def require(self, album):
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=album_prefix(album), MaxKeys=1)
        if not resp.get("KeyCount"):
            raise Error(f"В фотоархиве нет альбома с именем {album}")

    def photos(self, album):
        prefix = album_prefix(album)
        return [o["Key"][len(prefix):] for o in self._list(prefix) if o.get("Key", prefix) != prefix]

    def list(self, album):
        if album is None:
            names = self.albums()
        else:
            self.require(album)
            names = self.photos(album)
        for name in names:
            print(name)

    def upload(self, album, path):
        try:
            files = sorted(f for f in Path(path).iterdir() if f.is_file() and f.name.lower().endswith(PHOTO_SUFFIXES))
        except OSError as e:
            raise Error(f"Каталог {path} недоступен: {e.strerror}")
        if not files:
            raise Error(f"В каталоге {path} нет фотографий")
        prefix = album_prefix(album)
        self.s3.put_object(Bucket=self.bucket, Key=prefix, Body=b"")
        for f in files:
            self.s3.upload_file(str(f), self.bucket, prefix + f.name, ExtraArgs={"ContentType": "image/jpeg"})

    def download(self, album, path):
        self.require(album)
        target = Path(path)
        if not target.is_dir() or not os.access(target, os.W_OK | os.X_OK):
            raise Error(f"Каталог {path} недоступен для сохранения файлов")
        prefix = album_prefix(album)
        for name in self.photos(album):
            self.s3.download_file(self.bucket, prefix + name, str(target / name))

    def delete(self, album, photo):
        self.require(album)
        if photo is not None:
            key = album_prefix(album) + photo
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                    raise Error(f"В альбоме {album} нет фотографии {photo}")
                raise
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return
        keys = [{"Key": o["Key"]} for o in self._list(album_prefix(album), delimiter="")]
        for i in range(0, len(keys), 1000):
            resp = self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys[i:i + 1000], "Quiet": True})
            if resp.get("Errors"):
                raise Error(f"Не удалось удалить {resp['Errors'][0]['Key']}: {resp['Errors'][0]['Message']}")

    def mksite(self):
        self.s3.put_bucket_acl(Bucket=self.bucket, ACL="public-read")
        self.s3.put_bucket_website(
            Bucket=self.bucket,
            WebsiteConfiguration={"IndexDocument": {"Suffix": "index.html"}, "ErrorDocument": {"Key": "error.html"}},
        )
        albums = self.albums()
        for n, album in enumerate(albums, 1):
            self._put_page(f"album{n}.html", album_page(album, self.photos(album)))
        self._put_page("index.html", index_page(albums))
        self._put_page("error.html", ERROR_PAGE)
        # Страницы альбомов, оставшиеся от прошлого mksite, когда альбомов было больше.
        pages = {f"album{n}.html" for n in range(1, len(albums) + 1)}
        stale = [{"Key": o["Key"]} for o in self._list("album", delimiter="")
                 if re.fullmatch(r"album\d+\.html", o["Key"]) and o["Key"] not in pages]
        if stale:
            self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": stale, "Quiet": True})

    def _put_page(self, key, body):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body.encode(), ContentType="text/html; charset=utf-8")


def index_page(albums):
    if not albums:
        body = "    <p>Фотоархив пустой.</p>\n"
    else:
        items = "".join(
            f'        <li><a href="album{n}.html">{html.escape(a)}</a></li>\n' for n, a in enumerate(albums, 1)
        )
        body = f"    <ul>\n{items}    </ul>\n"
    return f"""<!doctype html>
<html>
    <head>
        <title>Фотоархив</title>
    </head>
<body>
    <h1>Фотоархив</h1>
{body}</body>
"""


def album_page(album, photos):
    # Экранируется только имя альбома; кавычки — часть шаблона.
    title = f'Фотоальбом "{html.escape(album)}"'
    if not photos:
        return f"""<!doctype html>
<html>
    <head>
        <title>{title}</title>
    </head>
    <body>
        <h1>{title}</h1>
        <p>Фотоальбом пустой.</p>
        <p>Вернуться на <a href="index.html">главную страницу</a> фотоархива</p>
    </body>
</html>
"""
    prefix = PHOTOS + quote(album, safe="") + "/"
    images = "".join(
        f'            <img src="{html.escape(prefix + quote(p, safe=""))}" data-title="{html.escape(p)}">\n'
        for p in photos
    )
    return f"""<!doctype html>
<html>
    <head>
        <title>{title}</title>
        <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/galleria/1.6.1/themes/classic/galleria.classic.min.css" />
        <style>
            .galleria{{ width: 960px; height: 540px; background: #000 }}
        </style>
        <script src="https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/galleria/1.6.1/galleria.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/galleria/1.6.1/themes/classic/galleria.classic.min.js"></script>
    </head>
    <body>
        <h1>{title}</h1>
        <div class="galleria">
{images}        </div>
        <p>Вернуться на <a href="index.html">главную страницу</a> фотоархива</p>
        <script>
            (function() {{
                Galleria.run('.galleria');
            }}());
        </script>
    </body>
</html>
"""


ERROR_PAGE = """<!doctype html>
<html>
    <head>
        <title>Фотоархив</title>
    </head>
<body>
    <h1>Ошибка</h1>
    <p>Ошибка при доступе к фотоархиву. Вернитесь на <a href="index.html">главную страницу</a> фотоархива.</p>
</body>
</html>
"""


def run(argv):
    if not all(os.environ.get(v) for v in ENV_VARS):
        raise Error("Не заданы переменные окружения")
    args = parse_args(argv)
    archive = Archive(os.environ["BUCKET"])
    if args.command == "list":
        archive.list(args.album)
    elif args.command == "upload":
        archive.upload(args.album, args.path)
    elif args.command == "download":
        archive.download(args.album, args.path)
    elif args.command == "delete":
        archive.delete(args.album, args.photo)
    else:
        archive.mksite()


def main():
    try:
        run(sys.argv[1:])
    except Error as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except (BotoCoreError, ClientError, OSError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
