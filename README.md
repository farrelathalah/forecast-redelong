# Forecast Redelong

Sistem otomatis prakiraan hujan multi-model untuk mendukung monitoring PLTA
Redelong. Produk utama menggunakan waktu WIB dan menyajikan hujan per jam,
akumulasi 3 jam, serta akumulasi area 24/48/72 jam.

Platform telah dikembangkan menjadi jaringan multi-site. PLTA Redelong tetap
menjadi site utama, sedangkan PLTM Besai Kemu memiliki forecast multi-titik,
histori, parameter engineering, geometri DAS teknis indikatif, dan skenario
debit proxy. Registry dapat ditambah melalui `config/sites.json` tanpa mengubah
engine forecast.

## Jaringan multi-site dan PLTM Besai Kemu

`build_utils/build_multisite_catalog.py` membuat `site_network.html`, globe 3D
yang menampilkan seluruh site beserta status kesiapan datanya. Tingkat kepastian
aset, data engineering, geometri DAS, dan model hidrologi ditampilkan secara
terpisah agar tidak tercampur.

PLTM Besai Kemu adalah aset run-of-river berkapasitas 2 × 3,5 MW yang mulai
beroperasi pada 8 Januari 2024 berdasarkan publikasi PT PLN (Persero). Paket
Besai Kemu menggunakan:

- bendung, headpond, powerhouse, dan Stasiun Sumberjaya dari dokumen engineering
  2018–2020;
- forecast BMKG serta enam model kuantitatif pada empat titik referensi;
- 16.436 hari histori NASA POWER Daily untuk 1981–2025;
- tabel hujan Stasiun Sumberjaya 1979–2008 dan FDC dari Review 2018;
- data debit historis yang dijelaskan pada FS/Review, termasuk data operasi PLTA
  Besai 1 sebagai baseline;
- luas DAS 496,74 km² dengan geometri teknis indikatif yang diikat ke outlet dan
  dikontrol terhadap luas Review 2020;
- forecast debit proxy H+1 sampai H+3 terhadap GloFAS;
- halaman `besai_kemu.html`, `besai_kemu_map.html`, dan
  `besai_kemu_discharge.html`.

Geometri DAS Besai Kemu bukan batas legal, as-built, atau delineasi DEM final
yang telah disetujui Engineering. Volume hujan selalu ditulis indikatif. NASA
POWER dan GloFAS merupakan proxy gridded, bukan observasi alat. Forecast debit
tidak disebut inflow operasional karena release PLTA Besai 1, AWLR, rating curve,
dan inflow aktual tidak tersedia dalam feed otomatis. Rincian terdapat pada
`docs/BESAI_KEMU_DATA_AND_HYDROLOGY.md`.

## Status area analisis Redelong

- PLTA Redelong adalah titik referensi/outlet dan tidak diberi bobot luas.
- GPM1–GPM6 dipakai sebagai **area analisis provisional** dengan total luas
  137,80 km².
- GPM Grid TamaTue hanya ditampilkan sebagai **titik pembanding eksternal**.
  Grid ini tidak masuk rata-rata area, volume hujan, maupun indikator operasional
  sampai batas DAS dan konektivitas alirannya dikonfirmasi.
- Luas 137,80 km² belum disebut sebagai luas DAS legal atau as-built.

Konfigurasi yang dapat diaudit berada di
`data/redelong/catchment_points.csv`.

## Sumber dan metode

Multi-model consensus kuantitatif memakai bobot sama untuk:

- ECMWF
- GFS
- ICON
- CMA GRAPES
- Météo-France
- UKMO

BMKG ditampilkan terpisah sebagai panduan kategoris resmi dan tidak diubah
menjadi besaran hujan numerik. KMA dinonaktifkan karena data operasionalnya tidak
tersedia, sedangkan MET Norway tidak dihitung sebagai model independen dari
ECMWF untuk wilayah global.

Nilai P10/P90 pada produk operasional adalah rentang skenario antar-model
deterministik, bukan probabilitas hujan yang sudah terkalibrasi. Nilai kosong
tidak pernah diubah menjadi 0 mm.

Akumulasi harian diberi kategori perhatian meteorologis BMKG: <0,5 mm/hari tidak
hujan/tidak terukur; 0,5–20 mm ringan; >20–50 mm sedang; >50–100 mm
lebat; dan >100 mm sangat lebat. Kategori tersebut bukan SOP bukaan pintu,
dispatch, penghentian unit, atau tindakan operasi perusahaan.

## Produk operasional

Setelah forecast selesai, `build_utils/build_redelong_operational.py` membuat:

- `redelong_operational.html`: ringkasan operator 24/48/72 jam;
- `redelong_operational_map.html`: peta peran spasial;
- `operational_3hour.csv`: hujan area per 3 jam;
- `operational_windows.csv`: akumulasi 24/48/72 jam;
- `operational_per_point_24h.csv`: perbandingan per titik/grid;
- `operational_source_status.csv`: quality control sumber;
- `bmkg_guidance.csv`: panduan kategoris BMKG;
- `redelong_operational.json`: API statis;
- `archive/<tahun>/<bulan>/<issue_time>/`: arsip forecast untuk validasi.

Modul hidrologi membuat `redelong_discharge.html` dan
`redelong_discharge_forecast.csv`. Metode, sumber proxy, pemisahan hindcast dan
validasi end-to-end, serta batas penggunaannya dijelaskan dalam
`docs/RAINFALL_TO_DISCHARGE.md`.

Seluruh output CSV memakai header eksplisit dan dapat dibuka langsung di Excel.
CSV/JSON di dashboard diperbarui otomatis pada setiap run. `index.html` tetap
menjadi portal utama; builder operasional tidak menimpanya.

## Globe 3D dan histori hujan

`build_utils/build_redelong_globe_history.py` membuat
`redelong_globe.html`, sebuah explorer spasial yang menggabungkan:

- globe interaktif dan fokus kamera ke Redelong;
- polygon GPM1–GPM6 dari paket geospasial proyek;
- forecast operasional terbaru dan jaringan titik forecast;
- klimatologi bulanan serta grafik tahunan GPM IMERG Final;
- metadata stasiun pembanding BMKG dan PU.

Histori GPM mencakup 2000–2024, dengan 24 tahun kalender lengkap untuk setiap
GPM1–GPM6 pada 2000–2023. Tahun 2024 tersedia sebagai tahun parsial dan tidak
dipakai dalam statistik tahunan lengkap. Data harian publik tersedia sebagai
`gpm_daily_history.csv`.

Batas polygon Redelong berasal dari `PLTA Redelong CLIP.shp` pada paket proyek.
Jumlah luas GPM1–GPM6 sekitar 137,80 km², tetapi statusnya tetap **batas area
analisis yang menunggu konfirmasi engineering**, bukan klaim batas legal.
Inventaris dan provenance dijelaskan dalam `docs/GEOSPATIAL_HISTORY_DATA.md`.

Forecast dijalankan setiap jam untuk empat hari kalender agar horizon 72 jam
sejak waktu penerbitan tetap lengkap. Halaman tiga hari interaktif dipertahankan,
sedangkan ringkasan operasional tersedia sebagai modul tambahan.

Sebelum deployment, `build_utils/validate_redelong_publish.py` memeriksa
kelengkapan minimal tiga model, horizon 24/48/72 jam, peran TamaTue, data portal,
dan sintaks JavaScript. Run yang tidak memenuhi kontrak tidak menggantikan
dashboard terakhir yang sehat.

`build_utils/apply_rev3_content.py` dijalankan setelah builder dan evaluator untuk
menyamakan narasi publik dengan laporan final. Modul ini menambahkan status
operasional Besai Kemu, batas penggunaan DAS dan debit, validasi lapangan
kualitatif, kategori hujan BMKG, serta `rev3_sync.json` sebagai bukti
machine-readable.

## Menjalankan lokal

```powershell
python weather_ensemble_multi_location.py `
  --mode forecast `
  --locations all `
  --locations-file locations.json `
  --timezone Asia/Jakarta `
  --sources BMKG,ECMWF,GFS,ICON,CMA,METEOFRANCE,UKMO `
  --per-hour `
  --forecast-range-days 4

python build_utils/build_redelong_operational.py --outputs outputs
python build_utils/fetch_glofas_discharge.py --outputs outputs
python build_utils/build_redelong_discharge.py --outputs outputs
python build_utils/build_redelong_globe_history.py --outputs outputs
python build_utils/build_besai_portal.py --outputs outputs
python build_utils/fetch_besai_discharge.py --outputs outputs
python build_utils/build_besai_hydrology.py --outputs outputs
python build_utils/build_multisite_catalog.py --outputs outputs
python build_utils/evaluate_forecast_accuracy.py
python build_utils/apply_rev3_content.py --outputs outputs
python build_utils/validate_redelong_publish.py --outputs outputs
python -m unittest discover -s tests -v
```

## Uji GitHub Actions tanpa mengubah website live

Workflow manual menyediakan input `validate_only`. Pilih `true` untuk
menjalankan forecast, evaluator, portal builder, sinkronisasi Rev.3, unit test,
dan publish quality gate tanpa menulis ke branch `gh-pages`. Hasil `outputs/`
tersedia sebagai artifact `forecast-redelong-validation-*` selama tujuh hari.

Push ke branch `feature/**` atau `validation/**` otomatis menjalankan build,
quality gate, unit test, dan upload artifact tanpa deployment. Push ke `main`
menjalankan rangkaian yang sama lalu menerbitkan hasil ke `gh-pages` jika seluruh
pemeriksaan lulus.

## Validasi forecast

Validasi memakai forecast yang telah diarsipkan berdasarkan issue time. Satu
issue paling awal per tanggal dipilih agar retry manual tidak menggandakan
sampel. Total hujan dibandingkan per lokasi dan hari, lalu dipisahkan menjadi
H+1, H+2, dan H+3. Hanya hari dengan sedikitnya 20/24 jam per model dan minimal
tiga model kuantitatif yang masuk evaluasi.

Ambang awal menggunakan jumlah tanggal unik, bukan jumlah titik lokasi, agar
titik-titik yang mengalami cuaca sama tidak dianggap sebagai sampel independen.
Workflow melengkapi tanggal matang menggunakan referensi gridded dan tidak
mencampurkan sumber berbeda menjadi satu nilai.

Pengecekan lapangan kualitatif hujan/tidak hujan telah dilakukan beberapa kali
dan kejadian hujan terkonfirmasi. Pengecekan itu tidak dimasukkan ke persentase
akurasi karena belum memiliki log tanggal, jam, lokasi, dan jumlah hujan yang
lengkap. Evaluasi numerik tetap disebut skill terhadap proxy gridded, bukan
akurasi lapangan.

## Batas penggunaan

Sistem merupakan decision-support prototype. Volume hujan bruto dihitung dengan
`P(mm) × A(km²) × 1000`. Forecast debit adalah model proxy harian yang
dikalibrasi terhadap GloFAS, bukan inflow atau debit lapangan terukur. Model belum
memasukkan release upstream real-time, operasi intake, routing sub-harian,
kehilangan air, maupun batas turbin. Keputusan operasi tetap berada pada operator
dan SOP perusahaan.
