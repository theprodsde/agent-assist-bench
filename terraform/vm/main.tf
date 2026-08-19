# ------------------------------------------------------------------
# Terraform module: VM deployment for AgentAssistBench agents
#
# Reference implementation uses the Azure provider (azurerm).
# To switch providers, replace the provider block and resource types
# while keeping the same variable interface and output contract.
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
# Networking
# ------------------------------------------------------------------

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azurerm_virtual_network" "vnet" {
  name                = var.vnet_name
  address_space       = ["10.0.0.0/16"]
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  tags                = var.tags
}

resource "azurerm_subnet" "subnet" {
  name                 = var.subnet_name
  resource_group_name  = data.azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_public_ip" "pip" {
  name                = "${var.agent_name}-pip"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_security_group" "nsg" {
  name                = "${var.agent_name}-nsg"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  tags                = var.tags

  security_rule {
    name                       = "allow-agent-port"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = tostring(var.agent_port)
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "allow-ssh"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "nic" {
  name                = "${var.agent_name}-nic"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  tags                = var.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.subnet.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.pip.id
  }
}

resource "azurerm_network_interface_security_group_association" "nic_nsg" {
  network_interface_id      = azurerm_network_interface.nic.id
  network_security_group_id = azurerm_network_security_group.nsg.id
}

# ------------------------------------------------------------------
# Virtual Machine
# ------------------------------------------------------------------

resource "azurerm_linux_virtual_machine" "vm" {
  name                = "${var.agent_name}-vm"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = var.region
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = merge(var.tags, {
    agent_name      = var.agent_name
    deployment_type = "virtual_machine"
    managed_by      = "terraform"
  })

  network_interface_ids = [
    azurerm_network_interface.nic.id,
  ]

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(var.ssh_public_key_path)
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = var.image_publisher
    offer     = var.image_offer
    sku       = var.image_sku
    version   = var.image_version
  }

  # Custom data script to start the agent service
  custom_data = base64encode(templatefile("${path.module}/cloud-init.tpl", {
    agent_name         = var.agent_name
    agent_port         = var.agent_port
    api_key_secret_ref = var.api_key_secret_ref
  }))
}
