# Data geospasial dan histori Forecast Redelong

Dokumen ini mencatat asal, peran, status, dan batas penggunaan data yang dipakai
oleh portal globe dan histori. Tujuannya agar tampilan publik tetap dapat diaudit
dan tidak membuat klaim yang lebih kuat daripada bukti sumbernya.

## Batas area analisis

| Data | Isi | Penggunaan publik | Status |
|---|---|---|---|
| `PLTA Redelong CLIP.shp` | Tujuh polygon berlabel GPM1–GPM6 dan GPM Grid TamaTue | Ditampilkan pada globe | Diberikan dalam paket proyek; metadata penetapan DAS belum tersedia |
| GPM1–GPM6 | Enam subarea, jumlah luas 137,799 km² | Forecast area, histori, dan visualisasi polygon | Area analisis provisional, menunggu konfirmasi engineering |
| GPM Grid TamaTue | Polygon 122,534 km² di luar enam subarea | Pembanding eksternal | Tidak masuk rata-rata area, volume hujan, atau luas 137,80 km² |
| Titik PLTA Redelong | 4,748139° LU, 96,977344° BT | Titik referensi/outlet | Tidak diberi bobot luas |

Luas dihitung dari geometri pada sistem koordinat WGS 84 / UTM Zone 47N sebelum
koordinat dikonversi ke WGS84 untuk web. Sebutan yang aman adalah **area analisis
Redelong dari paket data proyek**, bukan **DAS resmi**, sampai asal delineasi dan
konektivitas aliran dikonfirmasi oleh engineering.

## Histori hujan yang diterbitkan

| Sumber | Lokasi | Cakupan | Peran |
|---|---|---|---|
| NASA GPM IMERG Final Daily melalui Giovanni | GPM1–GPM6 | 1 Januari 2000–12 Desember 2024 | Histori harian publik, klimatologi bulanan, dan grafik tahunan |

Setiap GPM1–GPM6 memiliki 24 tahun kalender lengkap pada 2000–2023. Data 2024
parsial tetap dapat diunduh tetapi tidak dihitung sebagai tahun lengkap. CSV asal
menyimpan URL reproduksi Giovanni; pipeline mempertahankannya di metadata ringkas.

Nilai historis berasal dari enam sampling grid pada CSV berlabel GPM1–GPM6.
Polygon dengan label yang sama adalah bagian grid yang telah dipotong oleh batas
area pada shapefile. Karena pusat sampling sebuah sel raster dapat berada di luar
bagian polygon yang telah dipotong, posisi pusat grid tidak harus jatuh di dalam
polygon. Nilai ini tidak dinyatakan sebagai rerata seluruh piksel di dalam polygon.

IMERG adalah estimasi presipitasi berbasis satelit, bukan pengukuran penakar hujan
di site. Karena itu data ini cocok untuk histori spasial dan proxy observation,
tetapi tidak boleh disebut sebagai observasi lapangan PLTA.

## Data stasiun yang tidak diterbitkan ulang

Paket proyek juga memuat workbook hujan BMKG serta PU/BWS. Portal hanya
menampilkan nama, jaringan, koordinat, elevasi jika tersedia, rentang waktu, dan
jumlah hari hujan valid. Nilai harian mentah tidak disalin ke output publik sampai
izin redistribusinya dikonfirmasi.

| Jaringan | Stasiun | Cakupan data yang teridentifikasi |
|---|---|---|
| BMKG | Stasiun Meteorologi Malikussaleh | 2001-10-24–2025-10-23 |
| BMKG | Stasiun Meteorologi Cut Nyak Dhien Nagan Raya | 2010-01-01–2025-10-23 |
| BMKG | Stasiun Klimatologi Aceh | 2001-10-24–2025-10-23 |
| PU/BWS | TamaTue | 2015–2019 |
| PU | Blang Pante | 2014–2016 |
| PU/BWS | Jambo Aye | 2018–2019 |
| PU | Kp. Teupin Mane | Data valid tersebar pada 2008–2016 |

Stasiun Malikussaleh berada sekitar 53 km dari PLTA dan berketinggian rendah,
sehingga tidak dipakai sebagai kebenaran tunggal untuk catchment pegunungan
Redelong. Stasiun jauh tetap berguna sebagai pembanding regional, bukan pengganti
alat observasi di site.

## Pembagian data publik dan internal

- Publik: geometri area analisis, metadata stasiun, histori harian GPM yang telah
  diringkas, forecast operasional, serta catatan provenance.
- Internal: workbook mentah BMKG/PU dan berkas proyek asli yang hak
  redistribusinya belum dipastikan.
- Belum tersedia: observasi penakar hujan langsung di site, seri debit/inflow,
  serta metadata resmi penetapan batas DAS.

## Quality gate

`build_utils/validate_redelong_publish.py` menolak publikasi jika globe atau aset
utamanya hilang, enam polygon area tidak berjumlah sekitar 137–139 km², TamaTue
masuk ke catchment, histori lengkap kurang dari 24 tahun per zona, atau metadata
stasiun tidak ditandai `metadata_only`.

## Sumber teknis publik

- NASA GPM IMERG: <https://gpm.nasa.gov/data/imerg>
- NASA Giovanni: <https://giovanni.gsfc.nasa.gov/giovanni/>
- MapLibre GL JS: <https://maplibre.org/maplibre-gl-js/docs/>
