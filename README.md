# Forecast Redelong

Sistem otomatis prakiraan hujan multi-model untuk mendukung monitoring PLTA
Redelong. Produk utama menggunakan waktu WIB dan menyajikan hujan per jam,
akumulasi 3 jam, serta akumulasi area 24/48/72 jam.

Platform mulai digeneralisasi menjadi jaringan multi-site. PLTA Redelong tetap
menjadi site operasional utama, sedangkan PLTM Besai Kemu sudah memiliki
forecast titik empat hari dan explorer histori provisional. Registry yang dapat
ditambah tanpa mengubah engine berada di `config/sites.json`.

## Jaringan multi-site dan Besai Kemu

`build_utils/build_multisite_catalog.py` membuat `site_network.html`, globe 3D
yang menampilkan seluruh site beserta status kesiapan datanya. Site yang sudah
memiliki paket proyek dan site yang baru bersumber dari referensi publik tidak
ditampilkan seolah memiliki tingkat kepastian yang sama.

Paket awal PLTM Besai Kemu menggunakan:

- titik referensi publik `-4.87997, 104.50453` dan ADM4 Kemu
  `18.08.03.2017`;
- forecast BMKG serta enam model kuantitatif yang sama dengan Redelong;
- 16.436 hari histori NASA POWER Daily untuk 1981–2025;
- halaman `besai_kemu.html` dengan forecast empat hari, grafik tahunan, dan
  klimatologi bulanan.

Koordinat Besai Kemu masih berstatus provisional sampai posisi intake atau weir
dikonfirmasi oleh tim aset. Batas DAS belum didelineasi dan luasnya sengaja
dibiarkan kosong. Karena itu sistem memblokir klaim volume hujan dan debit untuk
Besai Kemu. NASA POWER juga ditulis sebagai proxy meteorologi gridded, bukan
observasi penakar hujan di site.

## Status area analisis

- PLTA Redelong adalah titik referensi/outlet dan tidak diberi bobot luas.
- GPM1–GPM6 dipakai sebagai **area analisis provisional** dengan total luas
  137,80 km².
- GPM Grid TamaTue hanya ditampilkan sebagai **titik pembanding eksternal**.
  Grid ini tidak masuk rata-rata area, volume hujan, maupun indikator operasional
  sampai batas DAS dan konektivitas alirannya dikonfirmasi.
- Luas 137,80 km² belum boleh disebut sebagai luas DAS resmi.

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

## Produk operasional

Setelah forecast selesai, `build_utils/build_redelong_operational.py` membuat:

- `redelong_operational.html`: ringkasan operator 24/48/72 jam yang melengkapi portal interaktif;
- `redelong_operational_map.html`: peta peran spasial;
- `operational_3hour.csv`: hujan area per 3 jam;
- `operational_windows.csv`: akumulasi 24/48/72 jam;
- `operational_per_point_24h.csv`: perbandingan per titik/grid;
- `operational_source_status.csv`: quality control sumber;
- `bmkg_guidance.csv`: panduan kategoris BMKG;
- `redelong_operational.json`: API statis;
- `archive/<tahun>/<bulan>/<issue_time>/`: arsip forecast untuk validasi.

Modul hidrologi tambahan membuat `redelong_discharge.html` dan
`redelong_discharge_forecast.csv`. Metode, sumber proxy, pemisahan hindcast dan
validasi end-to-end, serta batas penggunaannya dijelaskan dalam
`docs/RAINFALL_TO_DISCHARGE.md`.

Seluruh output CSV memakai header yang eksplisit dan dapat dibuka langsung di
Excel. Workbook `.xlsx` berformat khusus dapat dibuat sebagai snapshot laporan,
sedangkan CSV/JSON di dashboard diperbarui otomatis pada setiap run. `index.html`
tetap menjadi portal utama dengan peta, overview, dan dashboard per titik; builder
operasional tidak menimpanya.

## Globe 3D dan histori hujan

`build_utils/build_redelong_globe_history.py` membuat
`redelong_globe.html`, sebuah explorer spasial yang menggabungkan:

- globe interaktif dan fokus kamera ke Redelong;
- polygon GPM1–GPM6 dari paket geospasial proyek;
- forecast operasional terbaru dan jaringan titik forecast;
- klimatologi bulanan serta grafik tahunan GPM IMERG Final;
- metadata stasiun pembanding BMKG dan PU.

Histori GPM yang dipakai mencakup 2000–2024, dengan 24 tahun kalender lengkap
untuk setiap GPM1–GPM6 (2000–2023). Tahun 2024 tetap tersedia sebagai tahun
parsial dan tidak dipakai dalam statistik tahunan lengkap. Data harian publik
tersedia sebagai `gpm_daily_history.csv`.

Batas polygon berasal dari `PLTA Redelong CLIP.shp` pada paket data yang
diberikan untuk proyek. Jumlah luas GPM1–GPM6 adalah sekitar 137,80 km², tetapi
statusnya tetap **batas area analisis yang menunggu konfirmasi engineering**,
bukan klaim batas DAS resmi. Data mentah stasiun BMKG/PU tidak diterbitkan ulang
di GitHub Pages; portal hanya membawa metadata lokasi dan cakupan waktunya.
Inventaris, provenance, dan pembatasan publikasi dijelaskan dalam
`docs/GEOSPATIAL_HISTORY_DATA.md`.

Forecast dijalankan setiap jam untuk empat hari kalender agar horizon 72 jam
sejak waktu penerbitan tetap lengkap. Halaman tiga hari interaktif tetap
dipertahankan, sedangkan ringkasan operasional tersedia sebagai modul tambahan.

Sebelum deployment, `build_utils/validate_redelong_publish.py` memeriksa
kelengkapan minimal tiga model, horizon 24/48/72 jam, peran TamaTue, data portal,
dan sintaks JavaScript. Run yang tidak memenuhi kontrak tidak menggantikan
dashboard terakhir yang sehat. Evaluator hanya membandingkan akumulasi harian
yang memiliki sedikitnya 20/24 jam per model dan minimal tiga model valid.

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
python build_utils/build_multisite_catalog.py --outputs outputs
python build_utils/evaluate_forecast_accuracy.py
python build_utils/validate_redelong_publish.py --outputs outputs
python -m unittest discover -s tests -v
```

## Uji GitHub Actions tanpa mengubah website live

Workflow manual menyediakan input `validate_only`. Pilih `true` untuk
menjalankan forecast, evaluator, portal builder, dan publish quality gate tanpa
menulis ke branch `gh-pages`. Jika seluruh langkah lulus, hasil `outputs/`
tersedia sebagai artifact bernama `forecast-redelong-validation-*` selama tujuh
hari. Schedule dan trigger Google Apps Script yang tidak mengirim input ini
tetap memakai nilai default `false`, sehingga alur publikasi rutin tidak berubah.

Push ke branch `feature/**` atau `validation/**` juga otomatis menjalankan build,
quality gate, dan upload artifact validasi tanpa melakukan deployment. Dengan
demikian pengujian branch tidak lagi membutuhkan klik manual pada Actions.

## Validasi forecast

Validasi memakai forecast yang benar-benar telah diarsipkan berdasarkan issue
time. Satu issue paling awal per tanggal dipilih agar retry manual tidak
menggandakan sampel. Total hujan dibandingkan per lokasi dan hari, lalu hasil
dipisahkan menjadi H+1, H+2, dan H+3. Hanya hari dengan sedikitnya 20/24 jam per
model dan minimal tiga model kuantitatif yang masuk evaluasi.
Ambang awal menggunakan jumlah tanggal unik, bukan jumlah titik lokasi, agar
titik-titik yang mengalami cuaca sama tidak dianggap sebagai sampel independen.

Workflow mencoba melengkapi tanggal yang telah matang menggunakan GPM IMERG satu
kali per hari dan menyimpannya di `outputs/validation_archive/`. CHIRPS disimpan
sebagai pembanding tertunda jika IMERG belum tersedia. Kedua sumber tidak pernah
dicampur dalam satu nilai hujan. Kegagalan layanan proxy tidak menghentikan
publikasi forecast. Karena site tidak memiliki penakar hujan, metrik dinyatakan
sebagai skill terhadap referensi proxy gridded dan tidak disebut akurasi
lapangan. Status mesin dapat dibaca pada `evaluation_status.json`, sedangkan
pasangan dan metrik berada pada `evaluation_joined_daily.csv` dan
`evaluation_metrics.csv`.

## Pemeriksaan scheduler

Status `Completed` pada Google Apps Script hanya menyatakan fungsi telah selesai.
Keberhasilan dispatch dibuktikan oleh HTTP 204 dari GitHub dan munculnya run baru
pada Actions untuk commit `main` saat itu. Jika fungsi sengaja mencegah run
duplikat pada hari yang sama, log harus menyebutkan bahwa dispatch dilewati.

## Batas penggunaan

Sistem ini masih merupakan decision-support prototype. Akurasi forecast belum
dapat diklaim sebelum tersedia pasangan forecast–observation yang cukup.
Volume hujan bruto dihitung dengan `P(mm) × A(km²) × 1000`. Forecast debit yang
ditambahkan adalah model proxy harian yang dikalibrasi terhadap GloFAS, bukan
inflow atau debit lapangan terukur. Model belum memasukkan operasi waduk/intake,
routing sub-harian, kehilangan air, maupun batas turbin.
