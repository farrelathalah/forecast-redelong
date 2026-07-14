from pathlib import Path
import re

path = Path("outputs/redelong_overview.html")

if not path.exists():
    raise FileNotFoundError("outputs/redelong_overview.html belum ada. Jalankan make_forecast_redelong_overview.py dulu.")

html = path.read_text(encoding="utf-8")

# Bersihkan blok enhancement lama kalau sebelumnya sudah pernah ditambahkan
old_blocks = [
    ("<!-- FORECAST_REDELONG_PRESENTATION_GUIDE_START -->", "<!-- FORECAST_REDELONG_PRESENTATION_GUIDE_END -->"),
    ("<!-- FORECAST_REDELONG_CONTEXT_START -->", "<!-- FORECAST_REDELONG_CONTEXT_END -->"),
]

for start, end in old_blocks:
    html = re.sub(
        re.escape(start) + r".*?" + re.escape(end),
        "",
        html,
        flags=re.S,
    )

marker_start = "<!-- FORECAST_REDELONG_CONTEXT_START -->"
marker_end = "<!-- FORECAST_REDELONG_CONTEXT_END -->"

extra = f"""
{marker_start}
<section class="grid">
  <article class="panel full">
    <h2>Konteks sistem</h2>
    <p>
      Forecast Redelong disusun sebagai portal prakiraan hujan untuk area PLTA Redelong.
      GPM1–GPM6 membentuk area analisis catchment provisional, PLTA menjadi titik referensi
      outlet, dan Grid TamaTue dipertahankan hanya sebagai pembanding eksternal. Sistem ini tidak hanya menampilkan angka
      prakiraan, tetapi juga menyusun data menjadi bentuk yang lebih mudah dibaca melalui
      peta, dashboard lokasi, dan file keluaran yang dapat diperiksa ulang. Dengan susunan
      ini, pengguna dapat melihat gambaran umum dari homepage, membaca sebaran spasial
      melalui peta, lalu masuk ke dashboard per titik untuk melihat detail nilai hujan.
    </p>
    <p style="margin-top:14px">
      Fokus utama sistem ini adalah menyederhanakan hasil forecast multi-source menjadi
      informasi yang dapat dipakai untuk pemantauan awal. Karena cuaca, terutama hujan
      tropis, memiliki variasi ruang dan waktu yang tinggi, output sistem sebaiknya dibaca
      sebagai dukungan analisis, bukan sebagai angka tunggal yang berdiri sendiri.
    </p>
  </article>

  <article class="panel">
    <h2>Pendekatan multi-source</h2>
    <p>
      Konsensus kuantitatif menggunakan ECMWF, GFS, ICON, CMA, Meteo-France, dan UKMO
      dengan bobot sama agar pembacaan kondisi tidak bergantung pada satu model saja.
      Setiap model cuaca dapat memiliki karakter berbeda:
      ada model yang cenderung lebih basah, ada yang lebih konservatif, dan ada yang lebih
      baik untuk rentang waktu tertentu. Dengan menggabungkan beberapa sumber, sistem dapat
      memberikan gambaran yang lebih kaya tentang kemungkinan kondisi hujan.
    </p>
    <p style="margin-top:14px">
      BMKG ditampilkan terpisah sebagai panduan kategoris, bukan diubah menjadi nilai
      rain_mm. Perbedaan antar sumber justru penting untuk diperhatikan. Ketika banyak sumber
      menunjukkan sinyal hujan yang serupa, interpretasi menjadi lebih kuat. Sebaliknya,
      ketika sumber-sumber berbeda jauh, hasil forecast perlu dibaca dengan lebih hati-hati
      karena ketidakpastian antar model sedang lebih besar.
    </p>
  </article>

  <article class="panel">
    <h2>Interpretasi nilai hujan</h2>
    <p>
      Portal per titik menyediakan Mean, Max, dan P90 untuk screening data yang sedang
      ditampilkan. Modul Operasional DAS menyediakan ringkasan yang lebih tepat untuk
      keputusan waktu: akumulasi area 24/48/72 jam dan rentang P10–P90 antar-model pada
      periode yang sama.
    </p>
    <p style="margin-top:14px">
      P10–P90 tersebut adalah rentang skenario dari model deterministik, bukan probabilitas
      kejadian yang sudah dikalibrasi. Nilai kosong berarti coverage waktu atau model belum
      cukup; nilai itu tidak boleh diganti atau dibaca sebagai 0 mm.
    </p>
  </article>

  <article class="panel full">
    <h2>Rain Mean, Rain Max, dan Rain P90</h2>
    <ul>
      <li>
        <strong>Rain Mean</strong>
        <span>Pada produk operasional, rata-rata konsensus model untuk titik atau periode yang sama. Indikator ini membantu membaca kecenderungan umum tetapi tetap harus dilihat bersama rentang antar-model.</span>
      </li>
      <li>
        <strong>Rain Max</strong>
        <span>Nilai tertinggi pada kumpulan data yang sedang ditampilkan. Indikator ini berguna untuk screening, tetapi dapat dipengaruhi oleh satu model atau waktu yang sangat tinggi.</span>
      </li>
      <li>
        <strong>Rain P90</strong>
        <span>Pada modul operasional, batas atas rentang antar-model deterministik untuk periode yang sama. Nilai ini membantu membaca skenario lebih basah, tetapi bukan peluang 90% dan belum terkalibrasi sebagai probabilitas.</span>
      </li>
    </ul>
  </article>

  <article class="panel full">
    <h2>Makna persentil 90 dalam pembacaan risiko</h2>
    <p>
      Dalam modul operasional, P90 dihitung pada kumpulan hasil model untuk lokasi dan periode
      valid yang sebanding. P90 menunjukkan sisi atas perbedaan antar-model tanpa langsung
      memakai nilai maksimum. Karena anggotanya adalah model deterministik, P90 tidak boleh
      diterjemahkan sebagai peluang 90% hujan akan terjadi.
    </p>
    <p style="margin-top:14px">
      Dalam konteks monitoring hujan, P90 berguna karena skenario yang lebih basah sering kali
      tidak terlihat jelas jika hanya membaca rata-rata. Rata-rata dapat terlihat sedang,
      tetapi P90 yang lebih tinggi memberi sinyal bahwa ada skenario basah yang perlu
      diperhatikan. Sebaliknya, jika Mean, P90, dan Max sama-sama rendah, maka sinyal hujan
      dari data forecast cenderung lebih lemah.
    </p>
    <p style="margin-top:14px">
      Pembacaan yang baik biasanya tidak melihat satu indikator secara terpisah. Rain Mean
      memberi gambaran umum, Rain P90 menunjukkan sisi atas yang lebih relevan untuk kewaspadaan,
      dan Rain Max menunjukkan nilai tertinggi yang terdeteksi. Ketiganya bersama-sama
      membantu membaca apakah potensi hujan bersifat merata, terbatas pada sebagian sumber,
      atau hanya muncul sebagai nilai ekstrem tunggal.
    </p>
  </article>

  <article class="panel">
    <h2>Membaca peta hujan</h2>
    <p>
      Peta hujan digunakan untuk melihat sebaran nilai antar titik. Tampilan awal difokuskan
      pada PLTA dan GPM1–GPM6. TamaTue tersedia sebagai layer pembanding yang dapat dinyalakan,
      tetapi tidak memengaruhi agregasi area. Jika beberapa titik menunjukkan nilai P90 yang lebih tinggi,
      area tersebut dapat dipahami sebagai bagian yang memiliki sinyal hujan lebih kuat pada
      output forecast.
    </p>
    <p style="margin-top:14px">
      Peta sebaiknya dibaca sebagai tampilan awal. Setelah area dengan sinyal hujan terlihat,
      analisis dilanjutkan ke dashboard per titik untuk melihat grafik, nilai ringkasan,
      dan tabel data yang lebih detail.
    </p>
  </article>

  <article class="panel">
    <h2>Membaca dashboard per titik</h2>
    <p>
      Dashboard per titik berfungsi untuk memperjelas kondisi pada satu lokasi. Bagian atas
      dashboard menampilkan ringkasan hujan, sedangkan grafik dan tabel membantu melihat
      pola nilai forecast yang mendasarinya. Jika nilai P90 tinggi tetapi Rain Mean tidak
      terlalu tinggi, hal tersebut dapat menunjukkan adanya sebagian skenario yang lebih basah,
      bukan seluruh model sepakat pada hujan tinggi.
    </p>
    <p style="margin-top:14px">
      Tabel data mentah tetap disediakan agar output dapat ditelusuri kembali. Ini penting
      karena sistem forecast yang baik tidak hanya menampilkan hasil akhir, tetapi juga
      memungkinkan pengguna melihat sumber dan struktur data yang membentuk ringkasan tersebut.
    </p>
  </article>

  <article class="panel full">
    <h2>Status sumber data</h2>
    <p>
      Setiap sumber forecast dicatat dalam file status sumber. Informasi ini penting karena
      sistem bergantung pada koneksi dan ketersediaan data dari layanan eksternal. Jika sebuah
      sumber gagal karena timeout, handshake, atau gangguan koneksi, sistem masih dapat
      menghasilkan output dari sumber lain yang berhasil. Namun, jumlah sumber yang berhasil
      tetap perlu diperhatikan karena semakin sedikit sumber yang tersedia, semakin terbatas
      dasar ensemble yang digunakan.
    </p>
    <p style="margin-top:14px">
      Pada kondisi ideal, enam model kuantitatif aktif memberikan data untuk titik dan waktu target
      yang sama. Jika cakupan sumber tidak lengkap, hasil masih dapat dibaca, tetapi interpretasi
      perlu dibuat lebih hati-hati. Karena itu, status sumber bukan hanya catatan teknis,
      melainkan bagian dari penilaian kualitas output.
    </p>
  </article>

  <article class="panel">
    <h2>Posisi BMKG pada versi ini</h2>
    <p>
      Pada versi ini, BMKG aktif sebagai panduan kategoris resmi untuk referensi Bale Redelong.
      Kategori BMKG tidak dikonversi menjadi rain_mm dan tidak dicampurkan ke konsensus numerik,
      sehingga perbedaan makna data tetap terjaga. KMA dinonaktifkan karena data operasionalnya
      tidak tersedia, sedangkan MET Norway tidak dihitung sebagai anggota independen untuk
      menghindari penghitungan ganda informasi model yang berkaitan dengan ECMWF.
    </p>
  </article>

  <article class="panel">
    <h2>Status validasi</h2>
    <p>
      Akurasi numerik belum ditampilkan sebagai persentase karena sistem belum dibandingkan
      secara langsung dengan observasi aktual. Untuk menyatakan akurasi, forecast perlu
      diverifikasi terhadap data hujan aktual dari sumber seperti pengukuran PLTA, AWS,
      stasiun hujan, BMKG, GPM, atau sumber observasi lain yang relevan.
    </p>
    <p style="margin-top:14px">
      Tanpa proses verifikasi, angka persentase akurasi akan berisiko menyesatkan. Karena itu,
      versi ini lebih tepat diposisikan sebagai prototype monitoring dan visualisasi forecast
      yang sudah berjalan, sementara evaluasi performa menjadi tahap lanjutan.
    </p>
  </article>

  <article class="panel full">
    <h2>Arah evaluasi performa</h2>
    <p>
      Jika data observasi aktual sudah tersedia, sistem dapat dikembangkan ke tahap backtesting.
      Pada tahap tersebut, forecast dari periode sebelumnya dibandingkan dengan hujan aktual.
      Evaluasi dapat memakai metrik seperti MAE untuk melihat rata-rata kesalahan, RMSE untuk
      memberi penalti lebih besar pada error besar, bias untuk mengetahui kecenderungan terlalu
      tinggi atau terlalu rendah, serta metrik kejadian hujan seperti hit rate dan false alarm.
    </p>
    <p style="margin-top:14px">
      Dengan backtesting, sistem tidak hanya terlihat berjalan secara teknis, tetapi juga dapat
      dinilai performanya secara kuantitatif. Hasil evaluasi ini nantinya bisa dipakai untuk
      memilih sumber model yang paling konsisten, menyesuaikan bobot ensemble, atau menentukan
      ambang hujan yang lebih sesuai untuk kebutuhan monitoring PLTA Redelong.
    </p>
  </article>

  <article class="panel full">
    <h2>Batasan interpretasi</h2>
    <p>
      Forecast Redelong perlu dibaca dalam batasan sistem prakiraan cuaca. Model numerik
      memiliki resolusi spasial dan temporal tertentu, sehingga hujan lokal yang sangat
      dipengaruhi topografi dan proses konvektif tidak selalu tertangkap secara sempurna.
      Karena itu, output sistem sebaiknya dipakai sebagai informasi pendukung untuk
      meningkatkan kewaspadaan awal dan mempercepat pembacaan kondisi, bukan sebagai satu-satunya
      dasar keputusan operasional yang bersifat kritikal.
    </p>
    <p style="margin-top:14px">
      Nilai pada dashboard akan lebih kuat jika dibaca bersama informasi observasi, kondisi
      lapangan, dan update terbaru dari sumber resmi. Semakin lengkap sumber pembanding yang
      tersedia, semakin baik pula kualitas interpretasi terhadap forecast yang dihasilkan.
    </p>
    <p style="margin-top:14px">
      Volume hujan bruto yang ditampilkan bukan prediksi debit atau inflow. Konversi menuju
      debit memerlukan data luas DAS resmi, infiltrasi, kelembapan awal, routing, waktu tempuh,
      kondisi waduk, serta observasi debit untuk kalibrasi.
    </p>
  </article>
</section>
{marker_end}
"""

if "<footer>" in html:
    html = html.replace("<footer>", extra + "\n<footer>", 1)
else:
    html += extra

path.write_text(html, encoding="utf-8")

print("SUCCESS")
print("Overview diperkaya dengan penjelasan implisit dan lebih mendalam.")
