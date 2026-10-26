# River crossing camera routine

The iMac keeps its working files in `~/.server/giles-camera`. Its dedicated
GitHub deploy key can publish only to this repository. Login credentials, browser
profiles, originals and logs must never be copied into the repository.

`download.py` opens Moultrie headlessly, selects Tim P.'s shared gallery, scans
newest first until the requested date cutoff, and downloads only images labeled
Test whose detail page confirms camera `869736072671174`. It uses the displayed
capture date to handle delayed uploads. Website output contains at most one image
per Mountain Time calendar day, choosing the Test photo closest to 12:49 PM.
Images are compressed and re-encoded without source metadata; originals remain
on the iMac. Initial history: September 26–October 25, 2026; 21 available daily
photos were found, October 5–25.

`run.py` pulls the website with fast-forward only, checks the last 30 days for
missing/new images, and commits only `_data/camera.json` and `assets/camera`.
The growing public archive is retained; the lookback window does not delete old
published photos. A dirty checkout causes the job to stop rather than overwrite
work. Failed logins preserve the last published image. Check `status.json`,
`last-error.txt`, and the launch logs in the camera folder for run status.

The macOS LaunchAgent `com.giles.camera` runs at login and at 13:15 and 14:15
in the iMac's local timezone (configured as Mountain Time during setup). It runs
headlessly and opens no desktop windows. It requires the account's login session;
after a restart, someone must log in and unlock FileVault normally. Missed jobs
can run on wake; they cannot run while the Mac is powered off.

Runtime copies of `download.py`, `run.py`, and `auth.py` are installed directly in the camera folder.
Repository edits to them do not automatically replace the runtime copies.

Authentication snapshots are stored privately as `auth-state.json` (permissions
0600) in that folder, never in the website checkout. The snapshot includes session
cookies, local storage and session storage. Successful runs refresh the snapshot;
the login helper also saves it after a successful interactive login. Keeping only
a browser profile does not preserve all of these session-only values.

## Manual run on the iMac

```sh
~/.server/giles-camera/.venv/bin/python ~/.server/giles-camera/run.py
```

If Moultrie expires the session, renew it with the private headless login helper
in that folder and an SSH tunnel from the MacBook. Close the temporary debug
browser before a scheduled sync. Never publish the debugging port to the network.

## Disable scheduled runs

```sh
launchctl bootout gui/$(id -u)/com.giles.camera
```

The schedule file is `~/Library/LaunchAgents/com.giles.camera.plist`; this is the
one approved runtime file outside `~/.server` (apart from SSH authorization).
