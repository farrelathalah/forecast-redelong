# PLTM Besai Kemu: Data, Forecast, dan Hidrologi

## Status aset dan produk

PLTM Besai Kemu adalah pembangkit run-of-river berkapasitas 2 × 3,5 MW di
Kecamatan Banjit, Kabupaten Way Kanan, Lampung. PT PLN (Persero) menyatakan dua
unit tersebut mulai beroperasi pada 8 Januari 2024. Dengan demikian, status aset
adalah **operasional**.

Status operasional aset tidak berarti seluruh produk hidrologi pada dashboard
sudah menjadi data operasi. Forecast hujan merupakan decision-support
multi-model. Forecast debit tetap berstatus proxy karena tidak tersedia feed
AWLR, rating curve, inflow intake, dan release PLTA Besai 1 secara real-time.

Sumber status operasi:

- PT PLN (Persero), 10 Januari 2024:
  <https://web.pln.co.id/cms/media/siaran-pers/2024/01/awali-2024-pln-operasikan-dua-unit-pltm-kapasitas-35-mw-di-lampung-langkah-kebut-bauran-energi/>

## Hierarki dokumen engineering

Review Januari 2020 dipakai sebagai referensi utama karena merupakan revisi
terbaru. Nilai dari FS 2017 dan Review/Basic Design 2018 disimpan sebagai
pembanding dan tidak dirata-ratakan.

| Parameter | FS 2017 | Review 2018 | Review 2020 yang dipakai |
| --- | ---: | ---: | ---: |
| Luas DAS | 497 km² | 496,74 km² | 496,74 km² |
| Debit desain | 20,312 m³/s, Q38 | 21,00 m³/s; FDC Q40 18,35 m³/s | 21,59 m³/s, diadopsi 22 m³/s |
| Net head | 40,13 m | 38,80 m | 43,17 m pada tabel; narasi juga memuat 43,13 m |
| Energi tahunan | 39,735 GWh | 40,84 GWh | mengikuti kajian terbaru bila tersedia |
| Capacity factor | 65,00% | 66,56% | tidak dihitung ulang dari proxy dashboard |
| Debit ekologi | tidak dipakai | 1,243 m³/s | 0,60 m³/s |

Selisih 43,13 m dan 43,17 m pada Review 2020 dicatat secara eksplisit. Sistem
mempertahankan 43,17 m sebagai nilai tabel/adopted, tanpa menghapus keberadaan
angka 43,13 m pada narasi.

## Titik forecast

Forecast Besai memakai empat referensi spasial:

1. Bendung: 4°51'45.33" LS, 104°30'1.79" BT.
2. Headpond: 4°50'20.88" LS, 104°30'34.48" BT.
3. Powerhouse: 4°50'15.12" LS, 104°30'36.27" BT.
4. Stasiun Hujan Sumberjaya: 5°00'33.08" LS, 104°29'0.54" BT.

Nilai forecast harian adalah rata-rata setara dari titik yang tersedia untuk
masing-masing model, kemudian konsensus setara antar-model. Nilai ini merupakan
sampel spasial indikatif dan belum sama dengan integrasi raster pada seluruh
polygon DAS.

## Geometri DAS

Luas referensi DAS adalah 496,74 km². File
`besai_kemu_catchment.geojson` menyediakan geometri teknis indikatif yang:

- diikat ke koordinat outlet/bendung pada Review 2020;
- dikontrol terhadap luas 496,74 km²;
- menggunakan outline pada gambar FS sebagai kontrol bentuk;
- dipakai untuk orientasi peta dan perhitungan volume bruto indikatif.

Geometri tersebut **bukan** batas legal, as-built, atau delineasi DEM final yang
telah disetujui Engineering. Finalisasi engineering tetap harus menjalankan
ulang delineasi dengan DEMNAS atau DEM terkondisi setara, melakukan sink filling,
flow direction, flow accumulation, outlet snapping, pemeriksaan jaringan sungai,
dan persetujuan tim aset.

HydroBASINS dapat dipakai sebagai pemeriksaan independen karena menyediakan
sub-basin konsisten dari HydroSHEDS 15 arc-second, tetapi tidak otomatis
menggantikan batas desain proyek.

## Histori hujan

- `nasa_power_daily_1981_2025.csv.gz`: proxy meteorologi gridded harian.
- `sumberjaya_monthly_rainfall_1979_2008.csv`: transkripsi tabel stasiun hujan
  dari Review/Basic Design 2018.

Tabel Sumberjaya memuat 29 tahun. Tahun 1999 tidak tersedia. Nilai bulanan nol
pada 2001, 2002, dan 2007 dipertahankan sesuai dokumen dan ditandai untuk
peninjauan; nilai tersebut tidak otomatis dianggap bulan tanpa hujan.

## Data debit historis

Data debit bukan sepenuhnya tidak tersedia. Dokumen engineering menjelaskan:

- Review 2020 memakai data operasi jam-jaman PLTA Besai 1 periode 2004–2014,
  dengan kekosongan 2010–2011;
- data tersebut dikonversi menjadi debit harian dan ditransformasikan ke Besai
  Kemu menggunakan rasio luas DAS;
- FS 2017 menyebut data debit jam-jaman tailrace PLTA Besai periode 2004–2016;
- FDC, debit desain, debit irigasi, dan debit ekologi tersedia sebagai baseline.

Yang tidak tersedia dalam repository atau feed otomatis adalah deret mentah
jam-jaman, release upstream terbaru, AWLR/rating curve, dan inflow intake aktual.
Karena itu data historis dipakai sebagai konteks dan kontrol kewajaran, bukan
sebagai observasi real-time.

## Forecast debit

Model debit menggunakan bentuk harian yang dapat diaudit:

`Q(t) = c + a × Q(t-1) + b × P(t)`

Kalibrasi memakai hujan historis NASA POWER dan debit simulasi GloFAS. Koefisien
resesi dibatasi antara 0 dan 0,995 serta respons hujan tidak boleh negatif. Jika
hubungan hujan menjadi negatif akibat regulasi upstream, koefisien hujan dipotong
menjadi nol dan status regulasi ditulis di metadata.

Skenario air tersedia dihitung secara indikatif sebagai:

`Q tersedia = min(22, max(0, Q proxy - Q irigasi - Q ekologi))`

Pengurangan irigasi menggunakan 6,03 m³/s pada April–Mei dan 3,00 m³/s pada
bulan lain. Debit ekologi referensi adalah 0,60 m³/s.

PLTM Besai Kemu berada di hilir PLTA Besai 1. Tanpa release upstream aktual,
forecast tidak boleh disebut debit intake operasional.

## Kategori perhatian meteorologis

Akumulasi harian ditampilkan menggunakan kategori BMKG:

- tidak hujan/tidak terukur: <0,5 mm/hari;
- hujan ringan: 0,5–20 mm/hari;
- hujan sedang: >20–50 mm/hari;
- hujan lebat: >50–100 mm/hari;
- hujan sangat lebat: >100 mm/hari.

Kategori tersebut hanya menjadi tingkat perhatian meteorologis. Kategori tidak
menggantikan SOP bukaan pintu, dispatch, penghentian unit, atau keputusan
operasi perusahaan.

## Validasi

Validasi lapangan kualitatif hujan/tidak hujan telah dilakukan beberapa kali dan
kejadian hujan yang diprakirakan terkonfirmasi terjadi. Pemeriksaan tersebut tidak
dimasukkan ke persentase akurasi karena belum memiliki log tanggal, jam, lokasi,
dan jumlah hujan yang lengkap.

Evaluasi numerik tetap memakai forecast arsip dan referensi gridded yang dapat
dipasangkan berdasarkan tanggal serta lokasi. GloFAS dan NASA POWER bukan
observasi alat di site, sehingga metrik disebut skill terhadap proxy, bukan
akurasi lapangan.

Permintaan GloFAS tepat pada koordinat bendung memilih grid anak sungai dengan
Q40 sekitar 2 m³/s dan ditolak. Sampling digeser 0,05° ke barat agar API memilih
sel di `-4.874996, 104.475006`. Sel ini tetap merupakan proxy yang memerlukan
konfirmasi peta.

## Sumber publik pendukung

- Open-Meteo Flood API: <https://open-meteo.com/en/docs/flood-api>
- Open-Meteo Historical Weather API: <https://open-meteo.com/en/docs/historical-weather-api>
- HydroBASINS: <https://www.hydrosheds.org/products/hydrobasins>
- DEMNAS BIG: <https://www.big.go.id/content/product/demnas>
- Contoh kategori hujan harian BMKG:
  <https://staklim-yogya.bmkg.go.id/2024/02/06/analisis-curah-hujan-harian-6-februrari-2024/>

## Output otomatis

- `besai_kemu.html`: dashboard cuaca, histori, parameter engineering, dan konteks aset.
- `besai_kemu_map.html`: peta struktur dan DAS teknis indikatif.
- `besai_kemu_discharge.html`: forecast debit proxy H+1 sampai H+3.
- `besai_kemu_forecast.json`: konsensus forecast hujan multi-titik.
- `besai_kemu_discharge.json`: API statis hidrologi dan keterbatasan.
- `besai_kemu_discharge_forecast.csv`: forecast dan skenario debit.
- `besai_kemu_discharge_validation.csv`: metrik hindcast terhadap GloFAS.
- `besai_kemu_sumberjaya_monthly.csv`: tabel hujan engineering.
- `besai_kemu_fdc_2018.csv`: FDC historis yang dapat diaudit.
- `besai_kemu_structures.geojson`: titik struktur.
- `besai_kemu_catchment.geojson`: geometri DAS teknis indikatif.
- `rev3_sync.json`: bukti machine-readable bahwa narasi final telah diterapkan.
