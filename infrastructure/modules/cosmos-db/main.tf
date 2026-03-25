variable "account_name" {
  type = string
}

output "cosmos_account_name" {
  value = var.account_name
}
