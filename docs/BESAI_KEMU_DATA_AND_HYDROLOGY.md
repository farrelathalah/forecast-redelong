# PLTM Besai Kemu: Data, Forecast, dan Hidrologi

## Status produk

PLTM Besai Kemu menggunakan referensi engineering yang diberikan untuk proyek,
bukan lagi satu koordinat publik generik. Produk tetap berstatus
`engineering_document_reference_pending_asset_confirmation` karena koordinat
as-built dan polygon GIS DAS belum tersedia dalam paket yang diterima.

Angka luas DAS 496,74 km² boleh ditampilkan sebagai **luas menurut dokumen**,
tetapi tidak boleh digambar sebagai polygon buatan atau disebut batas DAS resmi.

## Hierarki revisi

Review Januari 2020 dipakai sebagai referensi utama karena merupakan revisi
terbaru. Nilai dari FS 2017 dan Review/Basic Design 2018 disimpan sebagai
pembanding dan tidak dirata-ratakan.

| Parameter | FS 2017 | Review 2018 | Review 2020 yang dipakai |
| --- | ---: | ---: | ---: |
| Luas DAS | 497 km² | 496,74 km² | 496,74 km² |
| Debit desain | 20,312 m³/s, Q38 | FDC Q40 18,35 m³/s | 21,59 m³/s, dibulatkan 22 m³/s |
| Net head | 40,13 m | 38,80 m pada ringkasan awal | 43,17 m |
| Debit ekologi | tidak dipakai | 1,243 m³/s | 0,6 m³/s berdasarkan referensi SIPPA |

Salinan Review 2020 yang diterima berhenti pada tabel risiko walaupun daftar isi
mencantumkan subbab kesimpulan. Karena itu semua parameter tetap membawa status
menunggu konfirmasi tim aset/engineering.

## Titik forecast

Forecast Besai memakai empat referensi spasial:

1. Bendung: 4°51'45.33" LS, 104°30'1.79" BT.
2. Headpond: 4°50'20.88" LS, 104°30'34.48" BT.
3. Powerhouse: 4°50'15.12" LS, 104°30'36.27" BT.
4. Stasiun Hujan Sumberjaya: 5°00'33.08" LS, 104°29'0.54" BT.

Nilai forecast harian adalah rata-rata setara dari titik yang tersedia untuk
masing-masing model, kemudian konsensus setara antar-model. Nilai ini merupakan
sampel spasial indikatif dan belum sama dengan integrasi polygon DAS.

## Histori hujan

- `nasa_power_daily_1981_2025.csv.gz`: proxy meteorologi gridded harian.
- `sumberjaya_monthly_rainfall_1979_2008.csv`: transkripsi tabel stasiun hujan
  dari Review/Basic Design 2018.

Tabel Sumberjaya memuat 29 tahun. Tahun 1999 tidak tersedia. Nilai bulanan nol
pada 2001, 2002, dan 2007 dipertahankan sesuai dokumen dan ditandai untuk
peninjauan; nilai tersebut tidak otomatis dianggap bulan tanpa hujan.

## Forecast debit

Model debit menggunakan bentuk harian yang dapat diaudit:

`Q(t) = c + a × Q(t-1) + b × P(t)`

Kalibrasi memakai hujan historis NASA POWER dan debit simulasi GloFAS. Koefisien
resesi dibatasi antara 0 dan 0,995 serta respons hujan tidak boleh negatif. Jika
hubungan hujan menjadi negatif akibat regulasi upstream, koefisien hujan dipotong
menjadi nol dan status regulasi ditulis di metadata.

Skenario air tersedia untuk PLTM dihitung secara indikatif sebagai:

`Q tersedia = min(22, max(0, Q proxy - Q irigasi - Q ekologi))`

Pengurangan irigasi menggunakan 6,03 m³/s pada April–Mei dan 3,00 m³/s pada
bulan lain. Debit ekologi referensi adalah 0,60 m³/s.

## Batas validasi

GloFAS dan NASA POWER adalah produk gridded, bukan observasi site. Dokumentasi
Open-Meteo menyatakan Flood API memilih sungai terbesar dalam sekitar 5 km dari
koordinat permintaan; kecocokan grid dengan Way Besai perlu diperiksa pada peta
GloFAS. Oleh karena itu metrik yang dipublikasikan adalah skill terhadap proxy,
bukan akurasi lapangan.

Permintaan tepat pada koordinat bendung memilih grid anak sungai dengan Q40
sekitar 2 m³/s, sehingga grid tersebut ditolak otomatis. Sampling GloFAS
digeser 0,05° ke barat agar API memilih sel sungai terdekat di
`-4.874996, 104.475006`. Workflow menghentikan publikasi jika Q40 historis grid
terpilih kurang dari 10 m³/s. Sel ini tetap menunggu konfirmasi pada peta GloFAS
dan tidak dianggap observasi Way Besai.

PLTM Besai Kemu berada di hilir PLTA Besai 1. Tanpa jadwal release atau data
operasi upstream, forecast tidak boleh disebut debit intake operasional. Data
AWLR dan release upstream dapat menggantikan proxy tanpa mengubah kontrak output.

## Sumber publik pendukung

- Open-Meteo Flood API: <https://open-meteo.com/en/docs/flood-api>
- HydroBASINS: <https://www.hydrosheds.org/products/hydrobasins>
- HydroBASINS technical documentation: <https://data.hydrosheds.org/file/technical-documentation/HydroBASINS_TechDoc_v1c.pdf>
- Open-Meteo Historical Weather API: <https://open-meteo.com/en/docs/historical-weather-api>

HydroBASINS dapat dipakai sebagai pemeriksaan independen setelah outlet final
disetujui, tetapi tidak menggantikan polygon desain proyek secara otomatis.

## Output otomatis

- `besai_kemu.html`: dashboard cuaca, histori, dan parameter engineering.
- `besai_kemu_map.html`: peta struktur tanpa polygon DAS palsu.
- `besai_kemu_discharge.html`: forecast debit proxy H+1 sampai H+3.
- `besai_kemu_forecast.json`: konsensus forecast hujan multi-titik.
- `besai_kemu_discharge.json`: API statis hidrologi dan keterbatasan.
- `besai_kemu_discharge_forecast.csv`: forecast dan skenario debit.
- `besai_kemu_discharge_validation.csv`: metrik hindcast terhadap GloFAS.
- `besai_kemu_sumberjaya_monthly.csv`: tabel hujan engineering.
- `besai_kemu_fdc_2018.csv`: FDC historis yang dapat diaudit.
- `besai_kemu_structures.geojson`: titik struktur dan fitur DAS tanpa geometri.
