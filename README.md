# Colorless Ports

A single-demo faceplate for colorless access ports. When a device connects, the matching jack lights. The legend is built from the colors in use. Click a lit jack to pin its details.

There is no application login. Switch, ClearPass, and Mist credentials are entered on the Admin page and stored in one SQLite file.

## The demo

EX4000, read through Mist. A pinned jack shows the port profile and the Mist role.

![EX4000 faceplate with port mge-0/0/0 pinned](docs/ex-faceplate.png)

AOS-CX 6200F, read from the switch. ClearPass adds the device detail on this faceplate when it is configured.

![AOS-CX 6200F faceplate with port 4 pinned](docs/aos-cx-faceplate.png)

## What's supported today

Two specific 12-port faceplates. A different 12-port model does not match the photo or the jack map.

**Aruba 6200F, 12 access ports.** The app reads the switch REST API directly. Ports `1/1/1` through `1/1/12` are the jacks on the left of the photo (odd on top, even on the bottom). The 1G, SFP, and management ports on the right stay dark. The color is the role the switch applied. ClearPass is optional: when it is configured it adds device name, type, and address to the Aruba popover. The demo runs, and the jacks still color, with ClearPass left blank. This faceplate does not call Mist.

**Juniper EX4000, 12 copper ports.** The app reads this switch through Mist only. There is no Junos session. Ports `0`–`11` (`ge-0/0/0`–`ge-0/0/11`, or `mge-0/0/0`–`mge-0/0/11`) are the copper jacks. On an EX4000-12MP the first four are usually `mge` and the rest `ge`. SFP ports (`xe-0/1/*`), management, and console stay dark. A Mist API token, the site ID, and the switch MAC are required for this faceplate. ClearPass is not queried. A radius-group role colors the jack when Mist applied one to the client. Otherwise the applied port profile does. A link with no client stays dark.

Not covered: other Aruba or Juniper chassis (including other 12-port models), Aruba Central as the data source, and a direct Junos connection.

`SUPPORT.md` is the field-by-field description of what each faceplate reads.

## Stand up the server

Docker and Docker Compose are the way to run it.

```bash
docker compose up --build
```

The service listens on port **8080**.

- Faceplate: `http://localhost:8080/`
- Admin: `http://localhost:8080/admin`
- Health: `http://localhost:8080/api/health`

Open Admin and fill in the switch. Add ClearPass only if you want the extra Aruba client fields. For the EX faceplate, fill in the Mist API token, site ID, and switch MAC, then the port profiles and roles. A blank password, client secret, or API token on Save keeps the value already stored. Admin never returns those secrets.

The poller runs only while a browser has the faceplate open.

Settings live in SQLite on the `colorless-data` volume (`/data/colorless.db` inside the container). `docker compose up --build` and `docker compose build --no-cache` keep that volume. `docker compose down` keeps it too. `docker compose down -v` deletes it.

The image does not mount the source tree. After a code change, run `docker compose up --build` again. A browser reload of the old container is still the old build.

### Without Docker

Python 3.12 and the packages in `requirements.txt`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The database file is `data/colorless.db` in this directory, unless `COLORLESS_DB` points somewhere else.
