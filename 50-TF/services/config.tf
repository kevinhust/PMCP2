# Config.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
  
  backend "s3" {
    bucket = "kevinw-p2"
    key    = "terraform/services/state"
    region = "us-east-1"
  }
}
