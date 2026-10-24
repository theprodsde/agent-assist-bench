# ------------------------------------------------------------------
# Terraform module: Azure Container Apps deployment for AgentAssistBench
#
# Each agent (Hermes / OpenClaw) gets its own resource group, Container
# App Environment, and Container App. The module creates the resource
# group rather than referencing an existing one — deploy Hermes and
# OpenClaw as independent stacks with separate state files.
#
# Image pulls: a user-assigned managed identity is created and, when
# acr_id is set, granted AcrPull on your registry — no admin passwords.
#
# Secrets: pass the agent API key either as a literal (api_key, stored
# as an ACA secret) or as a Key Vault secret ID
# (api_key_key_vault_secret_id) resolved at runtime via the managed
# identity. Additional secret env vars go in secret_env_vars; plain
# configuration goes in env_vars.
#
# Scaling: HTTP concurrent-request based. min_replicas = 0 scales to
# zero when idle (cheapest); use 1 to keep a warm replica.
#
# ADR-0006: Cloud-neutral — abstracted via variables
# ADR-0008: Infrastructure as code — all deployment codified
# ------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.62"
    }
  }
}

provider "azurerm" {
  features {}
}

locals {
  use_key_vault_api_key = var.api_key_key_vault_secret_id != ""
  registry_server       = split("/", var.container_image)[0]

  # ACA secret names must be lowercase alphanumeric/dash: MODEL_API_KEY -> model-api-key
  secret_env = {
    for env_name, env_value in var.secret_env_vars :
    env_name => {
      secret_name = lower(replace(env_name, "_", "-"))
      value       = env_value
    }
  }
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
# Managed identity — image pulls (AcrPull) and Key Vault secret reads
# ------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "app" {
  name                = "${var.agent_name}-identity"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  count                = var.acr_id != "" ? 1 : 0
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Requires the Key Vault to use RBAC authorization. For access-policy
# vaults, grant the identity Get/List secret permissions yourself and
# leave key_vault_id empty.
resource "azurerm_role_assignment" "kv_secrets" {
  count                = var.key_vault_id != "" ? 1 : 0
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# ------------------------------------------------------------------
# Container App — HTTP-based autoscaling
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

  # Role assignments must exist before the first image pull / secret read.
  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.kv_secrets,
  ]

  lifecycle {
    precondition {
      condition     = var.api_key != "" || var.api_key_key_vault_secret_id != ""
      error_message = "Set exactly one of api_key (literal) or api_key_key_vault_secret_id (Key Vault reference)."
    }
    precondition {
      condition     = !(var.api_key != "" && var.api_key_key_vault_secret_id != "")
      error_message = "api_key and api_key_key_vault_secret_id are mutually exclusive."
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "registry" {
    for_each = var.acr_id != "" ? [1] : []
    content {
      server   = local.registry_server
      identity = azurerm_user_assigned_identity.app.id
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = var.agent_name
      image  = var.container_image
      cpu    = var.cpu
      memory = var.memory

      env {
        name        = var.api_key_env_var_name
        secret_name = "api-key"
      }

      env {
        name  = "AGENT_PORT"
        value = tostring(var.container_port)
      }

      dynamic "env" {
        for_each = var.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value.secret_name
        }
      }

      # Readiness probe — ensures traffic only reaches healthy instances
      readiness_probe {
        transport               = "HTTP"
        port                    = var.container_port
        path                    = var.health_check_path
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

  # Agent API key: Key Vault reference resolved via managed identity, or a
  # literal value stored as an ACA secret — never a "reference" stored as text.
  dynamic "secret" {
    for_each = local.use_key_vault_api_key ? [1] : []
    content {
      name                = "api-key"
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = var.api_key_key_vault_secret_id
    }
  }

  dynamic "secret" {
    for_each = local.use_key_vault_api_key ? [] : [1]
    content {
      name  = "api-key"
      value = var.api_key
    }
  }

  dynamic "secret" {
    for_each = local.secret_env
    content {
      name  = secret.value.secret_name
      value = secret.value.value
    }
  }
}
