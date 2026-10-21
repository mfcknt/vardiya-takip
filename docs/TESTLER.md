# Doğrulama kaydı

Tarih: 20 Ekim 2026.

Ortamlar:
- **Windows (GitHub Actions `windows-2025-vs2026` sabit imajı, x64), Python 3.12** — tüm testler (Qt `offscreen` dâhil),
  PyInstaller paketi ve paketlenmiş `VardiyaBakim.exe` duman testi. Her `main` gönderiminde otomatik çalışır.
- Linux, Python 3.13 — Qt dışındaki testler (geliştirme sırasında).
- İlk teslim: macOS 27.0.1 / Apple Silicon, Python 3.12.14, SQLite 3.53.1, PySide6 6.10.2.

## Otomatik testler

**Windows’ta tüm testler geçti** (sayı her CI çalıştırmasında annotation olarak raporlanır). Arayüz testleri Qt `offscreen` platformuyla yürütülür.
CI, başarısız testleri GitHub annotation olarak yayınlar (`scripts/ci_annotate.py`).
Testlerin tamamı geçici klasörlerde veri oluşturur; gerçek uygulama verilerine erişmez.

```sh
python -m pytest -q
```

| Alan | Doğrulanan davranış |
|---|---|
| Giriş/çıkış | Aynı gün birden fazla çalışma, yeniden başlatmada açık kayıt |
| Yinelenen işlem | Aynı UUID ile tekrarın tek kayıt üretmesi, eski ekranın yeni kaydı kapatamaması |
| Eşzamanlılık | İki bağlantının aynı personel için yalnızca bir açık kayıt oluşturması |
| Veritabanı | Unique açık kayıt kuralı, transaction içinde hata olursa kayıt ve audit’in geri alınması |
| Hak ediş | Gece yarısı/ay sınırı, saniye hesabı, günlük yuvarlama, geçmiş ücretin korunması |
| Saat dilimi | Yaz/kış saati değişiminde 25 saatlik günün gerçek süresi |
| Açık çalışma | Geçici tahmin, bakiyeden dışlama, 24 saatten sonra yönetici kontrolü |
| Ödeme/avans | Tekrar önleme, gerekçeli iptal, devreden ve negatif bakiye |
| Düzeltme | Çakışma reddi, revision kontrolü, önce/sonra geçmişi, eski açık kaydı iptal etme |
| Yetki | Sahte/eksik/sona ermiş yönetici token’ının reddi, şifre değişiminde oturum iptali |
| PIN/parola | Tuz farkı, yanlış parola, zayıf/geçersiz PIN, düz metin saklamama |
| Deneme kilidi | Personel ve yönetici için 5 hata sonrası kilit; personel kilidinin yeniden açılışta korunması |
| Saat şüphesi | Geri/ileri sıçrama, yeniden açılışta geri saat ve uzun ara, gerekçeli onay |
| Bütünlük | Audit değiştirilemezliği, zincir değişikliği ve kayıt/denetim uyuşmazlığı |
| Yedek/kurtarma | Açık kaydı koruma, eski dosyayı arşivleme, bozuk hedefi kurtarma, doğru şifre otoritesi |
| Hatalı yedek | Bozuk kaynak/yanlış şifre/checksum reddi; hedefin korunması |
| Süreç çökmesi | Alt süreç commit öncesi zorla biter; değişiklik geri alınır, önceki commit korunur |
| Sıcak journal | Düşük SQLite cache ile journal diske yazdırılır, süreç aniden biter; açılış kurtarır |
| Süreç kilidi | İkinci uygulamanın engellenmesi ve kapanışta kilidin serbest kalması |
| CSV/XLSX | Unicode, doğru tutar/bakiye, formül enjeksiyonu önleme, negatif sayısal bakiye |
| Dışa aktarma hatası | Başarısız yeni rapor eski dosyayı bozmaz |
| Şema | Bilinmeyen veritabanı şeması sessizce değiştirilmez; her eski sürüm dosyası (`tests/fixtures`) güncellenir ve verisi korunur; eski dosya saklanır; başarısız güncelleme, daha yeni sürüm dosyası ve eski yedekten kurtarma; `--check`/`--upgrade` |
| Güncelleme (CI) | Önceki yayımlanmış sürüm kurulur, eski veri eklenir, yeni sürüm üstüne kurulur; veri değişmeden kalır, `--upgrade` ve `--check` geçer |
| Sürüm arşivi | Kurulum, zip ve kaynak kodu SHA-256 ile doğrulanarak arşivlenir; yanlış indirme klasör bırakmaz; arşiv üzerine yazılmaz; bozulan/eksik dosya bulunur; sertifikasız Python’da sistem curl’ü |
| Sistem sağlığı | Yedek yok/eski, az disk, günlük bütünlük denetimi; kiosk sayısı ve yönetici sayfası; günlük dosyası 4 MB ile sınırlı |
| Kurtarma anahtarı | Kurulumda oluşur, açık saklanmaz, tek kullanımlık, yenisi eskisini iptal eder, yönetici gibi kilitlenir, zayıf yeni kod anahtarı harcamaz, tuş takımıyla 20 rakam, ayarlardan yenileme |
| Kapalı dönem | Yalnızca biten ve kaydı olan ay; açık/incelemeli kayıt varken reddedilir; kapalı ayda ekleme, düzeltme, iptal, ödeme engeli; 05:00 sınırını aşan kayıt; kapanış bakiyesiyle rapor = tam hesap; tek tek yeniden açma; iş günü saati değişince yeniden hesap; meta oynanırsa bütünlük hatası |
| Kişiye özel kilit | Kilitlenen kişinin PIN penceresi tuş takımını gizler, kod almaz, kendiliğinden kapanır; yeniden açılınca kilit görünür; diğer personel ve yönetici girebilir; mesaj kimin kilitli olduğunu söyler |
| Personel kendi ayı | PIN ister ve kilide sayılır; yalnız kendi kayıtları, iptaller hariç, açık kayıt dahil; tutar yok; kayıt oluşturmaz |
| Makbuz | Tutar yazıyla (bin/yüz kuralları, kuruş), metin kaçışlı, iptal edilmiş ödemeye makbuz yok, PDF üretimi |
| Arka plan ve küçük ekran | Günlük yedek ve bütünlük denetimi arayüz dışında, hatası kioskta görünür; 1024 px’te hiçbir yönetici sayfası yana kaymaz, düğme satırları ve filtre alt satıra geçer, kutucuklar 2×2 olur |
| Qt arayüzü | PIN düğmeleri, giriş/çıkış, iptal, yanlış PIN, arama, yönetici sekmeleri ve kapanma |
| Performans | 3 yıl × 30 personel veride çakışma denetimi < 0,5 sn; günlük yedek süreç başına bir kez doğrulanır |
| Çakışma algoritması | Yeni sıralı tarama, eski self-join ile 400 rastgele veri kümesinde ve kenar durumlarında aynı sonucu verir |
| Saat incelemesi | Uyarıda giriş/çıkış sürer ve işaretlenir; düzeltme işareti kaldırır; uzun ara yalnızca bildirim |
| Kademeli kilit | 30 sn → 5 dk; doğru PIN sayacı sıfırlar; yönetici gerekçeyle kilidi kaldırır; ana ekranda görünür |
| Yedek saklama | Son 30 gün + ay başları + son 20 kapanış; elle alınan ve diğer dosyalara dokunulmaz |
| Filtreler | Hazır dönemler (ay/yıl/hafta sınırları), ‹ › gün gün ve bugünden ileri gitmez, özel aralık yalnızca “filtrele” ile uygulanır, dönem sayfalar arasında ortak, hak edişte personel filtresi, dışa aktarma ekrandaki dönemi kullanır, son 1000 işlem, yeni personel filtre listesine eklenir |
| Ekran metinleri | Süreler “92 sa 30 dk”, ekranda saniyesiz saat, işlem geçmişinde kod yerine isim, çift tıklayınca düzenleme, kioskta yalnızca “yönetici için N not var” |
| TL biçimi | 1.500,50 / 1500.50 / 1.500 girişleri; 1.440,00 gösterimi; hatalı tutar reddi |
| Konsol kodlaması | Bakım aracı cp1252 yönlendirilmiş çıktıda Türkçe metinle çökmez |
| İş günü | 05:00 sınırı: gece 00:30 yarım saati önceki güne, 17–01 vardiyası tek güne; ay sonu; ayar ve denetim |
| Unutulan çıkış | Sınırda tek sefer işaretleme, turuncu kart, PIN uyarısı, kapatıp yeniden giriş, yönetici düzeltmesi |
| Windows kilidi | İkinci uygulama örneği kilit dosyasını okurken çökmeden “başka uygulamada açık” der |

Süreç çökmesi testleri gerçek donanım elektrik kesintisinin veya disk kontrolcüsü arızasının
birebir karşılığı değildir. SQLite FULL senkronizasyonu ve yedekler bu riskler için birlikte kullanılır.

## Paket ve görsel kontroller

- `pyproject.toml` üzerinden düzenlenebilir kurulum başarıyla tamamlandı.
- PyInstaller 6.18.0 ile yerel macOS klasör paketi üretildi.
- Paketlenmiş bakım aracı bir deneme veritabanında bütünlük denetimini başarıyla çalıştırdı.
- Paket, sistem saat dilimi arama yolu boşken (`PYTHONTZPATH=""`) Qt offscreen açılışıyla sınandı.
- Ana ekran, PIN penceresi ve yönetici hak ediş ekranı örnek verilerle çizdirilip görsel incelendi.
- Ekran görüntüleri: `docs/ekranlar/` (CI her `main` gönderiminde `scripts/screenshots.py` ile
  Windows’ta yeniden üretir ve `ci-screenshots` dalına yükler).
- Görsellerdeki kişiler ve tutarlar yalnızca örnektir; projede hazır personel veritabanı bulunmaz.

## Windows CI’ın bulduğu ve düzeltilen hatalar

- İkinci uygulama örneği, Windows’ta kilitli bayttan okurken `PermissionError` ile çöküyordu (ilk teslimde de vardı).
- Paketlenmiş `VardiyaBakim.exe`, çıktısı yönlendirildiğinde Türkçe karakterde `UnicodeEncodeError` ile çöküyordu.

## Henüz doğrulanmayanlar

- Grafik `VardiyaTakip.exe`’nin gerçek bir masaüstünde elle açılması (CI ekransızdır; bakım aracı ve
  arayüz testleri çalıştı).
- Gerçek dokunmatik Windows cihaz, Windows ekran klavyesi, DPI/çoklu monitör davranışı.
- Hedef Microsoft Excel uygulamasında açılış; XLSX içerikleri openpyxl ile tekrar okunarak denetlendi.
- Donanım güç kesintisi, hasarlı disk, antivirüs/SmartScreen ve kod imzası.
- Düşük donanımlı gerçek Windows bilgisayarda performans; ölçümler CI ve Linux üzerindedir.

Windows hedef cihaz kabul adımları için `WINDOWS.md` dosyasına bakın.
