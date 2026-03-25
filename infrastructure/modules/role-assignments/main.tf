variable "principal_id" {
  type = string
}

output "assigned_principal_id" {
  value = var.principal_id
}
