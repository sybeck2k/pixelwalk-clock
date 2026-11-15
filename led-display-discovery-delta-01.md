# LED display Pi: discovery delta 01 (sensor drivers, DKMS, kernel)

**Base:** `~/led-display-discovery.md`, the revision ending at **§9.4** ("Implications for the new app"). That base file is unchanged; this file lists only what changed after it.
**Date:** 2026-11-15, 18:00–18:55 CET. All actions were approved by the owner unless marked otherwise.
Legend as in the base: **[V]** verified by command or file, **[I]** inferred.

---

## D0. Summary for the planner

1. **The VEML7700 light-sensor driver was replaced** with a fixed version. **Its sysfs interface changed** (D1.3). The AHT20 and BMP280 drivers are unchanged.
2. **All three custom drivers are now managed by DKMS** and rebuild automatically on kernel updates (D2). Base §3.1's "a kernel upgrade will silently drop all three sensors" no longer applies. **Owner decision: keep the custom drivers** rather than the mainline BMP280/AHT20 drivers, because the upstream drivers had issues; that's why the local builds exist. Treat the base §9.4 suggestion of switching to mainline drivers as rejected.
3. **A new kernel (6.8.0-1068-raspi) is installed and will boot on the next reboot.** It came in as a side effect of installing `linux-headers-raspi` and was not intended (D3). DKMS modules for it are built and verified, **but a boot into it has not been tested yet.**
4. **Not changed:** boot config (`config.txt`, `cmdline.txt`), services, the Node app, the matrix library, and the AHT20/BMP280 sources.

---

## D1. VEML7700 driver fix

### D1.1 Specifications used [V]
- Vishay datasheet **84286 Rev. 1.8 (28-Nov-2024)**:
  - ALS_IT (bits 9:6): `1100`=25 ms, `1000`=50, **`0000`=100**, `0001`=200, `0010`=400, `0011`=800 ms.
  - ALS_GAIN (bits 12:11): `00`=×1, `01`=×2, `10`=×1/8, `11`=×1/4.
  - Resolution **0.0042 lx/count at ×2 / 800 ms**, doubling for each halving of gain or integration time. Vishay corrected this in 2024 from 0.0036 lx/count.
- Vishay app note **84323 (rev. 06-Mar-2025)**:
  - **Gain ×1/×2 is non-linear above ~100 lx and must not be used there.** Above that, use ×1/8 or ×1/4.
  - Correction formula for low gain: `6.0135e-13·x⁴ − 9.3924e-9·x³ + 8.1488e-5·x² + 1.0023·x`, with x in uncorrected lux.
- **Unit-test finding:** the polynomial is only fitted up to 10 klx (its Fig. 9 axis). At 140 klx it gives about 2×10⁸ lx; ESPHome's docs also warn of large sunlight errors. The new driver applies it up to 10 klx and keeps the 10 klx factor (×1.479) above that. **That high-lux behaviour is an approximation of mine, not a Vishay formula.**

### D1.2 What was wrong in the old driver (base §9.3 items 1–5, 13–16) [V]
- **Integration time decoded wrongly:** 3 bits instead of 4, and code 0 treated as 25 ms instead of 100 ms, so the scale was 4× off.
- **Wrong scale:** it printed thousandths of a lux. Even after the Node app's ×1000, readings were about 23% high; at 100 ms and gain ×1 the true resolution is 0.0672 lx/count.
- **Overflow:** 32-bit arithmetic wrapped above ~3 klx, so bright light read near 0.
- **Ran at ×1 permanently**, i.e. non-linear above 100 lx with no correction.
- Common to all three drivers, fixed only for the VEML7700:
  - stale values on read errors;
  - zeros before the first sample;
  - possible deadlock when writing `poll_ms`;
  - `poll_ms=0` allowed.

### D1.3 New behaviour and **sysfs interface** (`/sys/bus/i2c/devices/1-0010/`) [V]

| File | Mode | Meaning |
|---|---|---|
| `illuminance` | r | **true lux**, 3 decimals. **Use this in the new app.** |
| `lux` | r | legacy unit: **kilolux**, 6 decimals (= `illuminance`/1000). Kept so the old Node app (which multiplies by 1000) gets true lux. |
| `raw` | r | ALS counts 0–65535 |
| `resolution` | r | lx/count of the range `raw` was taken in |
| `gain` | r | `2`, `1`, `1/4`, `1/8` (**now a string**; previously a raw code, rw) |
| `itime_ms` | r | integration time in ms (**replaces** the old `itime` file) |
| `range` | rw | 0–3; writing one fixes the range and turns `auto_range` off |
| `auto_range` | rw | 1 (default) / 0 |
| `poll_ms` | rw | default 1000, clamped to 100–60000; deadlock fixed |

- **Errors:** reads of `illuminance`, `lux` and `raw` fail with **EAGAIN** before the first sample (≈0.2–1.8 s after load) and with **EIO** if the last I2C read failed or no valid sample arrived for max(5×poll_ms, 5 s). In Python this is an `OSError` from `open().read()`. The new app should treat it as "no reading" and keep its last brightness.
- **Auto-ranging, with hysteresis**, following the app note (×1/×2 only below ~100 lx):

  | Range | Gain / IT | lx/count | Band |
  |---|---|---|---|
  | 0 | ×2 / 800 ms | 0.0042 | dark to ~84 lx |
  | 1 | ×2 / 100 ms | 0.0336 | ~34–100 lx |
  | 2 | ×1/8 / 100 ms + correction | 0.5376 | ~54 lx–27 klx |
  | 3 | ×1/8 / 25 ms + correction | 2.1504 | >~21 klx, max ~208 klx after correction |

  A range switch skips the next sample(s) for 2×IT + 10 ms. Response is 1–2 poll periods per range step.
- **Implications for the new app [I]:**
  - Lux is now usable as absolute (typical Vishay accuracy, not per-unit calibrated).
  - Night-time resolution is about 0.004 lx (the old driver stepped in ~0.7 lx), so a brightness curve can use log(lux) over roughly 0.1 lx to 10 klx.
  - Values are about 20% lower than the old driver gave below 100 lx, and different above (now corrected and not wrapping).

### D1.4 Verification [V]
- **Unit test:** a user-space build of the exact driver conversion code, run with `-fsanitize=signed-integer-overflow`.
  - Resolutions match the datasheet.
  - App-note example: 1500 lx → 1658.14 (app note: 1658).
  - Integer vs floating-point polynomial within ≤ 0.001 lx up to 10 klx.
  - Monotonic over 0–141 klx, no overflow; every range switch lands inside the next range's band.
- **Build:** clean, no warnings. srcversion **`75B91918A493885FE443D96`**.
- **Live test:** 90 s at 0.5 s sampling; the owner used a phone torch and then covered the sensor. 145 samples, **0 errors**.

  | Condition | Reading | Ranges |
  |---|---|---|
  | Room (evening) | **2.72 lx** steady ±0.01 (old driver: constant `0.003`) | 0 |
  | Torch | up to **2,129 lx** | 0→1→2 in ~2 s |
  | Covered | **0.45–0.53 lx** | 2→1→0 in ~1.3 s |

### D1.5 Files [V]
- **`~/veml7700_driver/`** is now the fixed version, under **local git**:
  - `237cb31` original baseline
  - `c844a7f` fix
  - `19f5afa` DKMS packaging

  It also contains new `dkms.conf` and `Kbuild` files.
- The old folder (19 files, including old build outputs) is archived as **`~/veml7700_driver.orig-2026-11-15.tar.gz`**. Its `veml7700.c` is byte-identical (SHA-256) to the git baseline.
- The old modules, previously hand-installed in `/lib/modules/6.8.0-1020-raspi/updates/`, were moved to **`/var/backups/sensor-modules-6.8.0-1020-raspi/`**:
  - `aht20.ko`, `bmp280.ko`, `veml7700.ko` (the fixed one, installed by hand at 18:19 before DKMS)
  - `veml7700.ko.orig-BA6372E0` (the original VEML7700 module)

---

## D2. DKMS (base §9.7 option 1, approved) [V]

- **Packages:** `dkms 3.0.11-1ubuntu13` and `linux-headers-raspi` (see D3 for everything this pulled in).
- Registered packages, source copies in `/usr/src/<name>-<ver>/` (only `*.c`, `Kbuild`, `dkms.conf`):

  | DKMS package | Module | Source copied from |
  |---|---|---|
  | `veml7700-local/1.1` | veml7700 | `~/veml7700_driver` (fixed) |
  | `aht20-local/1.0` | aht20 | `~/aht20_driver` (unchanged source) |
  | `bmp280-local/1.0` | bmp280 | `~/bmp280_driver` (unchanged source) |

- `dkms.conf`: builds with `make -C ${kernel_source_dir} M=… modules` through a minimal **`Kbuild`** file (`obj-m := <name>.o`), because the existing Makefiles hardcode `$(shell uname -r)`, the *running* kernel. Installs to `/updates/dkms`, `AUTOINSTALL="yes"`. `dkms.conf` and `Kbuild` were added to all three `~/*_driver` folders.
- **Installed for both kernels.** `dkms status` shows all six "installed" with no warnings. Modules live in `/lib/modules/<kernel>/updates/dkms/*.ko.zst`.
- **Name resolution checked** with `modinfo -k <kernel> -F filename,srcversion`:
  - All three resolve to `updates/dkms/` on both kernels, including `bmp280` on 6.8.0-1068, which has an in-tree `bmp280.ko.zst` (`/etc/depmod.d` search order is `updates ubuntu built-in`). `blacklist bmp280_i2c` still keeps the mainline I2C front-end away.
  - srcversions on disk for both kernels equal the running modules: veml7700 `75B91918…`, aht20 `E0EF7CCF…`, bmp280 `0F228F69…`.
- **Hooks present:** `/etc/kernel/postinst.d/dkms` (runs on kernel install) and `/etc/kernel/header_postinst.d/dkms` (runs on headers install). With `linux-headers-raspi` installed, future `apt upgrade`s bring matching headers, and DKMS builds the modules before the reboot.
- **Hiccup, fixed:** the first `dkms install` for 6.8.0-1020 silently skipped installing, because it took the hand-installed `updates/*.ko` files as its own ("Diff between built and installed module"). After those were moved out, 1020 briefly had no veml7700/aht20 module on disk (the running modules were unaffected). Fixed with `dkms install --force` for 1020 and re-verified.
- **Cost:** about 100 MB of headers per kernel version; each kernel update adds a few minutes of build time on the Pi 3. [I]

### D2.1 How to change a driver from now on [I, procedure]
DKMS builds from the copy in `/usr/src`, **not** from `~/*_driver`. After editing a driver:
1. Bump `PACKAGE_VERSION` in its `dkms.conf` (e.g. `1.2`).
2. `sudo mkdir /usr/src/<pkg>-<ver> && sudo install -m 644 <name>.c Kbuild dkms.conf /usr/src/<pkg>-<ver>/`
3. `sudo dkms remove <pkg>/<oldver> --all && sudo dkms add -m <pkg> -v <ver> && sudo dkms install <pkg>/<ver>` (for each installed kernel: `-k <kernel>`).
4. Reload: `sudo rmmod <name> && sudo modprobe <name>`.

---

## D3. Unintended kernel install (not approved as such) [V]
- `apt-get install --no-install-recommends dkms linux-headers-raspi` **also installed `linux-image-6.8.0-1068-raspi` and `linux-modules-6.8.0-1068-raspi` and upgraded the `linux-image-raspi` meta-package**, because the headers meta-package requires the matching kernel. I did not check this dependency first.
- Full list:
  - **New:** `dkms`, `dpkg-dev`, `libdpkg-perl`, `bzip2`, `lto-disabled-list`, `linux-headers-raspi`, `linux-headers-6.8.0-1068-raspi`, `linux-raspi-headers-6.8.0-1068`, `linux-image-6.8.0-1068-raspi`, `linux-modules-6.8.0-1068-raspi`.
  - **Upgraded:** `dpkg`, `libbz2-1.0`, `linux-image-raspi`.
  - +247 MB on disk; `/` is now 10% used, 51 GB free.
- **Next boot = 6.8.0-1068.** `/boot/firmware/vmlinuz` was rewritten at 18:41:58 and is 12,574,072 bytes, the same size as `vmlinuz-6.8.0-1068-raspi`. The previous kernel is kept as `/boot/firmware/vmlinuz.bak` (12,334,997 bytes = 6.8.0-1020), with `/boot/vmlinuz.old` and `initrd.img.old` → 1020. A new `initrd.img-6.8.0-1068-raspi` was generated at 18:41:33 from the current `/etc/modprobe.d` (blacklists included). [I: content not listed, because `lsinitramfs` takes minutes on the Pi 3]
- **Not yet tested:** an actual boot into 1068. Sensors, PIR daemon (libgpiod), the matrix library (hzeller `/dev/gpiomem` access) and the `rgbmatrix` Python module are all expected to work [I: same 6.8 series, the userspace ABI is unchanged], but this needs a reboot to confirm. The Python `rgbmatrix` module does not depend on the kernel version.
- Base §1 "Kernel 6.8.0-1020" will read 6.8.0-1068 after the next reboot.

---

## D4. Changes to base-report statements
| Base § | Base says | Now |
|---|---|---|
| §0.2, §3.1 | modules are kernel-locked; a kernel upgrade drops all three sensors | DKMS rebuilds automatically (D2). Still true that a kernel update without headers would fail, but `linux-headers-raspi` is now installed. |
| §3.3 | VEML7700 `lux` semantics, `gain`/`itime` codes, lux maths and accuracy notes | superseded by D1.3 |
| §3.3 sample | `1-0010/lux = 0.007` (old driver) | new driver gives true lux in `illuminance` (e.g. 2.72 lx in the evening room) |
| §9.1 | installed modules at `/lib/modules/6.8.0-1020-raspi/updates/*.ko` | now `/lib/modules/<k>/updates/dkms/*.ko.zst` for 1020 and 1068; old files in `/var/backups/sensor-modules-6.8.0-1020-raspi/` |
| §9.1 | no driver folder under git | `~/veml7700_driver` has local git; aht20/bmp280 still don't |
| §9.3 items 1–5 | VEML7700 maths bugs | **fixed** |
| §9.3 items 13–16 | stale values, boot zeros, `poll_ms` deadlock, `poll_ms=0` | **fixed for VEML7700 only; still present in AHT20 and BMP280** |
| §9.3 items 6–12 | AHT20/BMP280 issues | unchanged |
| §9.4 | consider mainline IIO/hwmon drivers | **owner decision: keep the custom drivers** |

## D5. Open items
1. **Reboot into 6.8.0-1068 and verify:** the three sensors (`/sys/bus/i2c/devices/1-00{10,38,77}`), the PIR daemon, and a matrix demo.
   - Fallback if 1068 misbehaves [I]: the old kernel is still installed. Booting it means pointing the firmware at the backups (`kernel=vmlinuz.bak`, `initramfs initrd.img.bak followkernel` in `config.txt`), or `sudo apt remove linux-image-6.8.0-1068-raspi` while running 1020, then `sudo flash-kernel`. Both are boot-config changes and need owner approval.
2. The AHT20/BMP280 drivers still have the stale-value, boot-zero and `poll_ms` deadlock issues (base §9.3 items 13–16). The fix pattern from the VEML7700 driver applies directly.
3. Put `~/aht20_driver` and `~/bmp280_driver` under git (they now contain the new `dkms.conf` and `Kbuild` files).
4. Remaining kernel-package updates: other packages may also have updates pending. `apt upgrade` is now safe for the sensors, but still changes the system.

---

## D6. Post-reboot verification on 6.8.0-1068 (owner rebooted, 2026-11-15 ~18:55) [V]
- `uname -r` = **6.8.0-1068-raspi**. All three modules loaded from `updates/dkms/*.ko.zst`, with srcversions identical to before (veml7700 `75B91918…`, aht20 `E0EF7CCF…`, bmp280 `0F228F69…`). `1-0010/1-0038/1-0077` are bound to their custom drivers; `dkms status` shows all six installed with no warnings. D5 item 1 is done for the sensors and PIR; the matrix panel has not been tested yet.
- Readings at ~2 min uptime: `illuminance` 1.852 lx (raw 441, range 0), AHT20 23.643 °C / 43.690 %RH, BMP280 24.75 °C / 994.90 hPa. No driver errors in dmesg.
- PIR: `pir_sensor.socket` and `.service` active, `/tmp/gpio_event.sock` present (`srw-rw---- ubuntu ubuntu`).
- `~/led-venv`: `import rgbmatrix` OK, Pillow 11.3.0. The module is kernel-independent.
- dmesg `vc_sm_cma: module verification failed … tainting kernel`: this is **Ubuntu's own in-tree module** (`kernel/drivers/staging/vc04_services/vc-sm-cma/`) shipping unsigned in this kernel package. It is informational only and not caused by the custom drivers, which taint the kernel too ("loading out-of-tree module").
- **NEW: under-voltage during boot.** dmesg shows `hwmon hwmon1: Undervoltage detected!` at 19.4 s and `Voltage normalised` at 23.5 s; `vcgencmd get_throttled` = **`0x50000`** (bit 16: under-voltage has occurred; bit 18: throttling has occurred). No current under-voltage (`in0_lcrit_alarm` 0; low bits 0). Before this boot it was `0x0` (base §1). CPU 65–68 °C at load ~1.2 just after boot.
  - [I] The boot peak (filesystem checks, DKMS and initramfs work being done, services starting) briefly pulled the 5 V rail below ~4.63 V. That points to a marginal supply or cable for the Pi. It matters for the clock if the panel and the Pi share a supply, because bright frames draw amps. To ask the owner: PSU rating (official Pi 3 supply is 5.1 V / 2.5 A), whether the panel has its own supply, and to re-check `get_throttled` after the matrix has run at full brightness.

---

## D7. AHT20 and BMP280 fixes (owner-approved, 2026-11-15 ~19:05) [V]
**Owner note on D6:** the power supply is fine; ignore the boot-time under-voltage.

- **Git:** `~/aht20_driver` and `~/bmp280_driver` are now local git repos (D5 item 3 done):

  | Repo | Original baseline (as running) | DKMS packaging (1.0) | Fix (1.1) |
  |---|---|---|---|
  | aht20 | `dc4f475` | `a64b709` | `26edc7e` |
  | bmp280 | `7080ce3` | `470c017` | `c9c3358` |

  The baselines were checked identical to the running modules and to `/usr/src/*-1.0` before committing.
- **Fixed in both** (base §9.3 items 13–16; D5 item 2 done):
  - Reads of `temperature`/`humidity` (AHT20) and `temp`/`pressure` (BMP280) return **EAGAIN** before the first measurement (previously `0.000`) and **EIO** if the last measurement failed or none succeeded for max(5×poll_ms, 5 s) (previously the old value forever).
  - `poll_ms` store re-arms with `mod_delayed_work()` outside the mutex (no deadlock) and is clamped to 100–60000.
  - First measurement 100 ms after probe instead of after `poll_ms`.
  - `remove()` drops sysfs before cancelling the work.
  - BMP280 additionally ignores the `0x80000` "no measurement" data value seen right after reset.
  - **Unchanged:** file names, output formats, compensation maths, sensor configuration. Base §9.3 items 6–12 (AHT20 CRC unchecked, sign bug between −1 and 0 °C in both, BMP280 continuous max-rate mode, BMP280 wait loops without timeout, station vs sea-level pressure) are **not** addressed.
- **Build:** no code warnings. "compiler differs from the one used to build the kernel" is only the GCC 13.3.0 Ubuntu package revision (`~24.04` vs the kernel's `~24.04.1`).
- **Live test** (module swapped with `rmmod`/`insmod` from the repo folder):

  | Check | AHT20 | BMP280 |
  |---|---|---|
  | First read after load | EAGAIN at +62 ms, valid at +166 ms | EAGAIN at +55 ms, valid at +136 ms |
  | Values vs old driver | identical within noise | identical within noise |
  | 300 rapid `poll_ms` writes (100/150/200 ms) under `timeout 60`, concurrent 400 reads | completed, 0 read errors | completed, 0 read errors |
  | Clamp | 0→100, 999999→60000 | 0→100, 999999→60000 |
  | Updates after restoring 1000 ms | yes | yes |
  | dmesg | clean | clean |

  **Not tested:** the EIO path (needs a real sensor failure); reviewed in code only, as for the VEML7700.
- **DKMS:** `aht20-local` and `bmp280-local` were upgraded **1.0 → 1.1** for both kernels (1.0 removed with `--all`, `/usr/src/*-1.0` deleted, sources in git). Modules were reloaded through `modprobe`.

  | Module | DKMS | srcversion (loaded = on disk, both kernels) |
  |---|---|---|
  | veml7700 | `veml7700-local 1.1` | `75B91918A493885FE443D96` |
  | aht20 | `aht20-local 1.1` | `FE236BBEF5A711105AF5921` |
  | bmp280 | `bmp280-local 1.1` | `4F8FA1311B4780634591E9A` |

  Readings after reload: 1.848 lx, 23.671 °C / 43.524 %RH (AHT20), 24.75 °C / 994.80 hPa (BMP280).
- **Implication for the new app [I]:** all three sensors now behave the same way. Read sysfs and treat `OSError` (EAGAIN or EIO) as "no current reading". There's no need for app-side staleness heuristics or a boot-zero guard (base §9.4).
- **D5 open items now:** item 1 is partly done (sensors and PIR verified on 6.8.0-1068; the matrix panel has not been tested on the new kernel yet). Items 2 and 3 are done.

## D8. Matrix panel on 6.8.0-1068 (owner-approved) [V]
- `sudo timeout -s INT 15 ./demo -D0 --led-rows=64 --led-cols=64 --led-gpio-mapping=regular --led-slowdown-gpio=2 --led-pixel-mapper="Rotate:270" --led-brightness=80 --led-show-refresh` (C++ demo binary built against the old library commit `d10f518`, base §2.1). It ran 15 s and was stopped by the timeout (exit 124). No errors, no new dmesg lines. **The matrix library works on the new kernel** (`/dev/gpiomem` access, hardware pulsing).
- Refresh: 1430 samples; median **101.7 Hz**, mean 97.7, p5 72.7, p1 66.7, min **49.4**, max 110.4. On 6.8.0-1020 (base §6b) it was median 108.8, min 62.2. Load average before the run was 0.36.
- [I] It's not established whether the ~7 Hz lower median is the kernel or run-to-run variation: a 15 s run vs 20 s, and this session was active during the run. Earlier runs showed similar swings from other CPU load (base §8.8 vs §8.9). A longer comparison with the session idle would settle it. The owner hasn't yet reported whether anything looked different on the panel.
- D5 item 1 (post-reboot verification) is now done for the sensors, PIR, Python module and matrix.
