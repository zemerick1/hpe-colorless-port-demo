# What each faceplate talks to

The demo has two faceplates. A toggle on the demo page picks which chassis is drawn. AOS-CX colors come from switch roles. On the EX faceplate one source is live. Admin has an EX polling choice, Mist or Junos. Save applies it, and the other source stays filled in and idle. A Mist role colors the jack when the client has one, and the port profile colors it otherwise. On Junos the same name is the firewall filter. Those lists are separate from each other and from the Aruba role list. The FAQ on the faceplate says why the EX label changes with the source.

## AOS-CX

- The app logs into the switch REST API with the username and password from Admin. Later reads send the session token.
- The faceplate follows the chassis part number from `/system/subsystems`. Supported models are the 6200F 12-port (`R8Q72A`, `R8V13A`), the 6300F 24-port (`JL666A`, `S0G96A`), and the 6300M 24-port (`JL660A`). `platform_name` alone is not enough, so a 6200F 24-port or a 6300F 48-port stays blank.
- The 6200F lights `1/1/1` through `1/1/12`. The 6300F and the 6300M light `1/1/1` through `1/1/24`. SFP, console, and management ports stay dark. Both 24-port photos are fitted to the same frame, so the jack map stays in place. On the 6300M the copper block groups ports 1–8 and 9–24, so ports 9–12 sit slightly to the right of the 6300F jacks. If the part number is known but the interface list has a port that chassis does not have, the stage stays blank.
- The admin role name is the role on the switch. The jack uses that color when the name matches. The port popup shows the role the switch applied, including a role that is not in Admin. An unmatched role lights grey. The label is the legend text only.
- ClearPass is optional. It fills device name, device type, category, OS family, and IP on that faceplate only.
- Mist is not called for this faceplate.

## Juniper EX

- Two sources, and only one is polled. EX polling in Admin is the switch: choose Mist or Junos and Save. The other set of fields stays stored. Junos reads the switch REST API (`system services rest https`, port 3443 by default). Mist uses the API token, site ID, and switch MAC. Until a choice has been saved, a filled-in Junos host is the source, and otherwise Mist is.
- It does not ask ClearPass about EX clients.
- Copper ports `ge-0/0/0`–`ge-0/0/11` and `mge-0/0/0`–`mge-0/0/11` are the twelve jacks on the EX4000 photo. On an EX4000-12MP the first four are usually `mge` and the rest `ge`. SFP ports (`xe-0/1/*`), management, and console stay dark.
- Junos has no role object. Mist still calls it a Role. Mist pushes an ethernet-switching firewall filter of the same name (`EMPLOYEE`, `IOT`) only after that role is applied to a Switch Policy. In Mist, that firewall filter is the Switch Policy. A role that is not on a Switch Policy is never pushed, so the filter and the role never appear on the Junos device. The faceplate says Role for Mist and Firewall filter for Junos. Both names use the Roles list.
- On Mist, the role is the radius-group on the switch template, returned on the wired client as `dynamic_filter`. On Junos, the name is the filter on the authenticated dot1x session.
- A Mist client with no role uses the port profile Mist applied. On the API that field is `port_usage`. In the Mist UI it is `usage` and `reportedProfile` (for example `dot1x-only`). `configuredProfile` is not a second color. The Junos path has no port profile. An authenticated session with no filter lights gray.
- Roles are matched on the Roles list under Juniper/Mist. Profiles are matched on the Port profiles list. Neither list is the Aruba role list. A NAC rule, NAC tag, usermac label, or IdP role does not color the jack. Load from Junos reads ethernet-switching filters from the configuration and from the installed firewall table. Mist roles are often only in that table. Load from the Mist switch template reads `acl_tags` whose type is `radius_group` or `aruba_user_role`.
- A role, filter, or profile that is not on its card yet still lights gray, with its raw name, so it can be added.
- A link with no client stays dark, even when a profile is configured on the port. Mist reporting the port as authenticated, or a forwarding-table MAC count, still counts as a client when the wired-client search has not returned one yet.
