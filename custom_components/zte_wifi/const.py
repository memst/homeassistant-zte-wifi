"""Constants for the ZTE WiFi integration."""

from __future__ import annotations

DOMAIN = "zte_wifi"

DEFAULT_HOST = "http://192.168.2.1"
DEFAULT_INSTANCE_ID = "DEV.WIFI.AP6"
DEFAULT_LOGIN_TOKEN_PATH = "/function_module/login_module/login_page/logintoken_lua.lua"
DEFAULT_NAME = "ZTE WiFi"
DEFAULT_PAGE_PATH = "/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0"
DEFAULT_PATH = "/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua"

CONF_APPLY_PAYLOAD = "apply_payload"
CONF_INSTANCE_ID = "instance_id"
CONF_LOGIN_TOKEN_PATH = "login_token_path"
CONF_PAGE_PATH = "page_path"
CONF_PATH = "path"
