output "site_url" {
  value = "https://${local.site}/"
}

output "aws_access_key_id" {
  value = yandex_iam_service_account_static_access_key.cloudphoto.access_key
}

output "aws_secret_access_key" {
  value     = yandex_iam_service_account_static_access_key.cloudphoto.secret_key
  sensitive = true
}
