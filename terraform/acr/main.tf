# ------------------------------------------------------------------
# Azure Container Registry for storing Hermes and OpenClaw images
#
# Deploy once, then push images from CI/CD or local:
#   az acr login --name <registry_name>
#   docker tag hermes-agent <registry_name>.azurecr.io/hermes:latest
#   docker push <registry_name>.azurecr.io/hermes:latest
#
# Or build directly in ACR (no local Docker needed):
#   az acr build --registry <registry_name> --image hermes:latest --file docker/hermes/Dockerfile .
#   az acr build --registry <registry_name> --image openclaw:latest --file docker/openclaw/Dockerfile .
# ------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "acr_rg" {
  name     = var.resource_group_name
  location = var.region
  tags     = var.tags
}

resource "azurerm_container_registry" "acr" {
  name                = var.registry_name
  resource_group_name = azurerm_resource_group.acr_rg.name
  location            = azurerm_resource_group.acr_rg.location
  sku                 = var.sku
  admin_enabled       = true
  tags                = var.tags
}
