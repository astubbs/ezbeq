# ezbeq

A simple web browser for [beqcatalogue](https://beqcatalogue.readthedocs.io/en/latest/) which integrates with [minidsp-rs](https://github.com/mrene/minidsp-rs)
for local remote control of a minidsp.

# Setup

## Installation

ssh into your rpi and

    $ ssh pi@myrpi
    $ sudo apt install python3 python3-venv python3-pip libyaml-dev git
    $ mkdir python
    $ cd python
    $ python3 -m venv ezbeq
    $ cd ezbeq
    $ . bin/activate
    $ pip install git+https://github.com/3ll3d00d/ezbeq

Install minidsp-rs as per the provided instructionshttps://github.com/mrene/minidsp-rs#installation

## Running the app manually

    $ ssh pi@myrpi
    $ cd python/ezbeq
    $ . bin/activate
    $ ./bin/ezbeq
      Loading config from /home/pi/.ezbeq/ezbeq.yml
      2021-01-16 08:43:15,374 - twisted - INFO - __init__ - Serving ui from /home/pi/python/ezbeq/lib/python3.8/site-packages/ezbeq/ui

## Configuration

See `$HOME/.ezbeq/ezbeq.yml`

## Starting ezbeq on bootup

This is optional but recommended, it ensures the app starts automatically whenever the rpi boots up and makes
sure it restarts automatically if it ever crashes.

We will achieve this by creating and enabling a `systemd`_ service.

1) Create a file ezbeq.service in the appropriate location for your distro (e.g. ``/etc/systemd/system/`` for debian)::

```
[Unit]
Description=ezbeq
After=network.target

[Service]
Type=simple
User=myuser
WorkingDirectory=/home/pi
ExecStart=/home/pi/python/ezbeq/bin/ezbeq
Restart=always
RestartSec=1

[Install]
WantedBy=multi-user.target
```

2) enable the service and start it up::


    $ sudo systemctl enable ezbeq.service
    $ sudo service ezbeq start
    $ sudo journalctl -u ezbeq.service
    -- Logs begin at Sat 2019-08-17 12:17:02 BST, end at Sun 2019-08-18 21:58:43 BST. --
    Aug 18 21:58:36 swoop systemd[1]: Started ezbeq.


3) reboot and repeat step 2 to verify the recorder has automatically started
