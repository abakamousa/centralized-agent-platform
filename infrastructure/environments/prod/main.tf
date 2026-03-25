terraform {
  required_version = ">= 1.6.0"
}

module "aca_environment" {
  source = "../../modules/aca-environment"
  name   = "cap-prod-aca-env"
}

module "cosmos_db" {
  source       = "../../modules/cosmos-db"
  account_name = "cap-prod-cosmos"
}

module "role_assignments" {
  source       = "../../modules/role-assignments"
  principal_id = "00000000-0000-0000-0000-000000000001"
}
