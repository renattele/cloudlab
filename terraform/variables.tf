variable "folder_id" {
  description = "Идентификатор каталога Yandex Cloud, в котором создаются ресурсы"
  type        = string
}

variable "bucket_name" {
  description = "Имя бакета Yandex Object Storage (= BUCKET для cloudphoto), например photos.vvot12.itiscl.ru"
  type        = string
}

variable "domain" {
  description = "Доменная зона, в которую добавляются DNS-записи сайта, например vvot12.itiscl.ru"
  type        = string
}

variable "cert_id" {
  description = "ID сертификата Yandex Certificate Manager для домена сайта"
  type        = string
}

variable "dns_zone_id" {
  description = "ID зоны Yandex Cloud DNS для домена"
  type        = string
}
