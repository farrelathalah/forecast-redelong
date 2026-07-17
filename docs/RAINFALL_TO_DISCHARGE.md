# Forecast hujan ke debit PLTA Redelong

## Status

Modul ini adalah **prototype proxy-calibrated**, bukan model debit yang sudah
dikalibrasi terhadap AWLR atau pengukuran debit PLTA. Hasilnya dapat dipakai
untuk eksplorasi engineering dan membangun proses validasi, tetapi belum boleh
menjadi satu-satunya dasar keputusan keselamatan, bukaan pintu, atau komitmen
energi.

Besai Kemu sengaja belum diberi forecast debit. Koordinat outlet/intake dan
batas DAS-nya masih provisional, sehingga hujan area dan debit belum dapat
dihitung secara bertanggung jawab.

## Aliran data

1. Forecast source-level ECMWF, GFS, ICON, CMA, Météo-France, dan UKMO dihitung
   pada GPM1–GPM6.
2. Setiap titik diberi bobot luas polygon sehingga menghasilkan hujan area
   untuk tiga jendela 24 jam sejak issue time.
3. Model ARX harian mengubah hujan area menjadi debit:

   `Q(t) = c + a × Q(t-1) + b × P(t)`

4. `Q(t-1)` diinisialisasi dari GloFAS hari sebelum awal forecast.
5. Mean forecast hujan menghasilkan forecast debit utama. P10/P90 antar-model
   dan RMSE hindcast membentuk skenario rendah/tinggi; rentang ini bukan
   probabilitas terkalibrasi.

## Data kalibrasi dan validasi

- Hujan: NASA GPM IMERG Final Daily pada GPM1–GPM6, 2000 sampai 12 Desember
  2024, diagregasi dengan bobot area provisional 137,80 km².
- Debit referensi: GloFAS v4 melalui Open-Meteo Flood API. API memilih grid
  sungai 4,725006; 96,975006 untuk permintaan outlet PLTA 4,748139; 96,977344.
- GloFAS adalah debit simulasi gridded sekitar 5 km, bukan observasi alat.

Kalibrasi dan validasi dipisahkan menurut waktu. Validasi transformasi memakai
rolling hindcast lead 1–3 hari dengan hujan IMERG historis sebagai forcing.
Karena forcing ini sudah diketahui, metrik tersebut hanya menilai transformasi
hujan–debit terhadap GloFAS; bukan skill end-to-end forecast hujan.

Validasi end-to-end yang benar dikumpulkan dari forecast operasional yang
diarsipkan. Setelah tanggal valid matang, forecast debit dibandingkan dengan
GloFAS pada tanggal yang sama dan dipisahkan menurut lead. Status baru boleh
menjadi `preliminary_proxy_skill` setelah sedikitnya 30 pasangan per lead.
Status ini tetap tidak sama dengan akurasi lapangan.

## Output

- `redelong_discharge.html`: dashboard forecast, skenario, dan validasi proxy.
- `redelong_discharge_forecast.csv`: forecast debit lead 1–3 hari.
- `redelong_discharge.json`: payload mesin dan disclaimer.
- `redelong_discharge_validation.csv`: metrik rolling hindcast transformasi.
- `redelong_discharge_hindcast_pairs.csv`: pasangan hindcast historis.
- `redelong_discharge_end_to_end_pairs.csv`: pasangan forecast arsip yang sudah
  matang.
- `redelong_discharge_end_to_end_validation.csv`: metrik end-to-end jika sampel
  tersedia.
- `hydrology/glofas_discharge_metadata.json`: provenance grid dan sumber.

## Verifikasi yang masih diperlukan

1. Engineering mengonfirmasi outlet dan bahwa grid GloFAS memang mewakili
   sungai yang memasok PLTA.
2. Tim site menyediakan seri debit/AWLR, level–discharge rating curve, atau
   setidaknya catatan debit operasi bertimestamp.
3. Batas DAS 137,80 km² dikonfirmasi dan kebutuhan routing sub-harian ditinjau.
4. Lisensi/API untuk penggunaan produksi korporat dikonfirmasi; endpoint publik
   saat ini cocok untuk prototype dan validasi teknis.
5. Setelah data lapangan tersedia, parameter dikalibrasi ulang dan metrik proxy
   tidak dipakai sebagai pengganti akurasi lapangan.
