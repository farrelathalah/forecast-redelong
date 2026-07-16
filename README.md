# Forecast Redelong

Sistem otomatis prakiraan hujan multi-model untuk mendukung monitoring PLTA
Redelong. Produk utama menggunakan waktu WIB dan menyajikan hujan per jam,
akumulasi 3 jam, serta akumulasi area 24/48/72 jam.

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

Seluruh output CSV memakai header yang eksplisit dan dapat dibuka langsung di
Excel. Workbook `.xlsx` berformat khusus dapat dibuat sebagai snapshot laporan,
sedangkan CSV/JSON di dashboard diperbarui otomatis pada setiap run. `index.html`
tetap menjadi portal utama dengan peta, overview, dan dashboard per titik; builder
operasional tidak menimpanya.

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
Volume hujan bruto dihitung dengan `P(mm) × A(km²) × 1000`, tetapi bukan prediksi
debit atau inflow karena belum memasukkan infiltrasi, kelembapan awal, routing,
waktu tempuh, dan operasi waduk.
