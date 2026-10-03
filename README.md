# cloudphoto

Фотоархив в Yandex Object Storage: https://photos.vvot12.itiscl.ru/

## Сборка

```sh
pip install .
```

Инфраструктура: `cd terraform && YC_TOKEN=$(yc iam create-token) terraform apply`.

## Переменные окружения

- `BUCKET` — имя бакета
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — статический ключ (`terraform output`)

## Схема хранилища

```
photos/<альбом>/        пустой маркер альбома
photos/<альбом>/<имя>   фотография с исходным именем
index.html, error.html, album{N}.html
```

Ключ однозначно задаёт альбом и исходное имя файла с учётом регистра. Маркер хранит пустой альбом. Страницы сайта лежат вне `photos/` и не пересекаются с фотографиями. `/` в имени альбома запрещён. Отдельного индекса нет: префиксы S3 — единственный источник истины, рассинхронизироваться нечему.
