terraform {
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 1.5"
}

# Аутентификация — через переменную окружения YC_TOKEN.
provider "yandex" {
  folder_id = var.folder_id
}

locals {
  site = "photos.${var.domain}"
}

resource "yandex_iam_service_account" "cloudphoto" {
  name = "vvot12-cloudphoto"
}

resource "yandex_iam_service_account_static_access_key" "cloudphoto" {
  service_account_id = yandex_iam_service_account.cloudphoto.id
}

# Публичный доступ и хостинг сайта включает команда `cloudphoto mksite`.
resource "yandex_storage_bucket" "photos" {
  bucket    = var.bucket_name
  folder_id = var.folder_id

  https {
    certificate_id = var.cert_id
  }

  lifecycle {
    ignore_changes = [website] # задаётся командой mksite
    precondition {
      condition     = var.bucket_name == local.site
      error_message = "Для хостинга на своём домене имя бакета должно совпадать с доменом сайта (${local.site})."
    }
  }
}

# storage.admin нужен mksite для настройки публичного доступа и хостинга.
resource "yandex_storage_bucket_iam_binding" "cloudphoto" {
  bucket  = yandex_storage_bucket.photos.bucket
  role    = "storage.admin"
  members = ["serviceAccount:${yandex_iam_service_account.cloudphoto.id}"]
}

resource "yandex_dns_recordset" "photos" {
  zone_id = var.dns_zone_id
  name    = "${local.site}."
  type    = "CNAME"
  ttl     = 600
  data    = ["${var.bucket_name}.website.yandexcloud.net."]
}
