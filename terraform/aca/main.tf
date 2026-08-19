# ------------------------------------------------------------------
# Terraform module: Azure Container Apps deployment for AgentAssistBench
#
# Each agent (Hermes / OpenClaw) gets its own resource group, Container
# App Environment, and Container App. The module creates the resource
# group rather than referencing an existing one — deploy Hermes and
# OpenClaw as independent stacks with separate state files.
#
# Scaling: HTTP concurrent-request based, 1→10 replicas by default.
# Configuration is intentionally minimal.
#
# ADR-0006: Cloud-neutral — abstracted via variables
# ADR-0008: Infrastructure as code — all deployment codified
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

# ------------------------------------------------------------------
# Resource Group (created per agent — Hermes and OpenClaw are isolated)
# ------------------------------------------------------------------

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.region
  tags     = var.tags
}

# ------------------------------------------------------------------
# Log Analytics Workspace
# ------------------------------------------------------------------

resource "azurerm_log_analytics_workspace" "law" {
  name                = "${var.agent_name}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

# ------------------------------------------------------------------
# Container App Environment
# ------------------------------------------------------------------

resource "azurerm_container_app_environment" "env" {
  name                       = "${var.agent_name}-env"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = var.tags
}

# ------------------------------------------------------------------
# Container App — minimal config, HTTP-based autoscaling 1→10
# ------------------------------------------------------------------

resource "azurerm_container_app" "app" {
  name                         = "${var.agent_name}-ca"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags = merge(var.tags, {
    agent_name      = var.agent_name
    deployment_type = "managed_container"
    managed_by      = "terraform"
  })

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = var.agent_name
      image  = var.container_image
      cpu    = var.cpu
      memory = var.memory

      env {
        name        = "AGENT_API_KEY"
        secret_name = "api-key"
      }

      env {
        name  = "AGENT_PORT"
        value = tostring(var.container_port)
      }

      # Readiness probe — ensures traffic only reaches healthy instances
      readiness_probe {
        transport               = "HTTP"
        port                    = var.container_port
        path                    = var.health_check_path
        initial_delay           = 5
        interval_seconds        = 10
        timeout                 = 3
        failure_count_threshold = 3
      }

      # Liveness probe — restarts unhealthy containers
      liveness_probe {
        transport               = "HTTP"
        port                    = var.container_port
        path                    = var.health_check_path
        initial_delay           = 10
        interval_seconds        = 30
        timeout                 = 3
        failure_count_threshold = 3
      }
    }

    # HTTP-based autoscaling: scale on concurrent requests per replica
    # When concurrent requests exceed the threshold, ACA adds replicas (up to max)
    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = var.scale_concurrent_requests
    }
  }

  ingress {
    external_enabled = true
    target_port      = var.container_port
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  secret {
    name  = "api-key"
    value = var.api_key_secret_ref
  }
}
