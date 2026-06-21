Things to note:
- `$CURRENT_TS` is always a newly-generated current epoch time in millis.
- We should make sure that there's also always a cookie `_TESTCOOKIESUPPORT=1` in our requests.

1. GET on '/' page with no cookies returns an HTML with a line:
```
LoginFormObj.addParameter("_sessionTOKEN", "$LOGIN_FORM_TOKEN");
```
Where `$LOGIN_FORM_TOKEN` is some number we want to get.

2. GET on `/function_module/login_module/login_page/logintoken_lua.lua?_=$CURRENT_TS`
This returns an AJAX response with a login token that should be combined with the password.
3. POST on `/` with a payload:
`Username=admin&Password=$PASSWORD_HASH&action=login&_sessionTOKEN=$LOGIN_FORM_TOKEN`
Where `$PASSWORD_HASH` is the password put through the existing `_hash_password` function and `$LOGIN_FORM_TOKEN` is the value we got in step 1.

This results in HTTP 302 that also has a `Set-Cookie` parameter for `SID` cookie that we should set for the rest of the session.

4. GET on `/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0&_=$CURRENT_TS`
This should return HTML with a line:
`_sessionTmpToken = "$WLAN_PAGE_TOKEN"` which we should parse

5. POST to `/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua` with payload:
`IF_ACTION=Apply&Enable=0&_InstID=DEV.WIFI.AP6&_sessionTOKEN=$WLAN_PAGE_TOKEN`
