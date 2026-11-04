# What each faceplate talks to

The demo has two faceplates. A toggle on the demo page picks which chassis is drawn. AOS-CX colors come from switch roles. On the EX faceplate a Mist role colors the jack when the client has one, and the port profile colors it otherwise. Those lists are separate from each other and from the Aruba role list.

## AOS-CX

- The app logs into the switch REST API with the username and password from Admin. Later reads send the session token.
- ClearPass is optional. It fills device name, device type, category, OS family, and IP on that faceplate only.
- Mist is not called for this faceplate.

## Juniper EX

- The app reads the switch through the Mist API only, using the API token, site ID, and switch MAC from Admin.
- It does not open a Junos session.
- It does not ask ClearPass about EX clients.
- Copper ports `ge-0/0/0`–`ge-0/0/11` and `mge-0/0/0`–`mge-0/0/11` are the twelve jacks on the EX4000 photo. On an EX4000-12MP the first four are usually `mge` and the rest `ge`. SFP ports (`xe-0/1/*`), management, and console stay dark.
- A lit jack is a connected client. If Mist applied a role, that role colors the jack. The role is the radius-group on the switch template, returned on the wired client as `dynamic_filter`. This tenant starts with `EMPLOYEE` and `IOT`.
- A connected client with no role uses the port profile Mist applied. On the API that field is `port_usage`. In the Mist UI it is `usage` and `reportedProfile` (for example `dot1x-only`). `configuredProfile` is not a second color.
- Roles are matched on the Roles list under Juniper/Mist. Profiles are matched on the Port profiles list. Neither list is the Aruba role list. A NAC rule, NAC tag, usermac label, or IdP role does not color the jack.
- A role or profile that is not on its card yet still lights gray, with its raw name, so it can be added.
- A link with no client stays dark, even when a profile is configured on the port. Mist reporting the port as authenticated, or a forwarding-table MAC count, still counts as a client when the wired-client search has not returned one yet.
