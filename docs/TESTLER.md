# Doğrulama kaydı

Tarih: 20 Ekim 2026.

Ortam: macOS 27.0.1 / Apple Silicon, Python 3.12.14, SQLite 3.53.1,
PySide6 6.10.2, openpyxl 3.1.5, pytest 8.4.2.

## Otomatik testler

**55 test geçti.** Arayüz testleri Qt `offscreen` platformuyla yürütülür.
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
| Şema | Bilinmeyen veritabanı şeması sessizce değiştirilmez |
| Qt arayüzü | PIN düğmeleri, giriş/çıkış, iptal, yanlış PIN, arama, yönetici sekmeleri ve kapanma |

Süreç çökmesi testleri gerçek donanım elektrik kesintisinin veya disk kontrolcüsü arızasının
birebir karşılığı değildir. SQLite FULL senkronizasyonu ve yedekler bu riskler için birlikte kullanılır.

## Paket ve görsel kontroller

- `pyproject.toml` üzerinden düzenlenebilir kurulum başarıyla tamamlandı.
- PyInstaller 6.18.0 ile yerel macOS klasör paketi üretildi.
- Paketlenmiş bakım aracı bir deneme veritabanında bütünlük denetimini başarıyla çalıştırdı.
- Paket, sistem saat dilimi arama yolu boşken (`PYTHONTZPATH=""`) Qt offscreen açılışıyla sınandı.
- Ana ekran, PIN penceresi ve yönetici hak ediş ekranı örnek verilerle çizdirilip görsel incelendi.
- Ekran görüntüleri: `personel-ekrani.png`, `pin-ekrani.png`, `yonetici-ekrani.png`.
- Görsellerdeki kişiler ve tutarlar yalnızca örnektir; projede hazır personel veritabanı bulunmaz.

## Henüz doğrulanmayanlar

- Windows üzerinde test çalıştırma ve `.exe` üretme; verilen Windows iş akışı henüz uzakta çalıştırılmadı.
- Gerçek dokunmatik Windows cihaz, Windows ekran klavyesi, DPI/çoklu monitör davranışı.
- Hedef Microsoft Excel uygulamasında açılış; XLSX içerikleri openpyxl ile tekrar okunarak denetlendi.
- Donanım güç kesintisi, hasarlı disk, antivirüs/SmartScreen ve kod imzası.
- Büyük ölçekli performans; MVP tek işletme/tek bilgisayar içindir.

Windows hedef cihaz kabul adımları için `WINDOWS.md` dosyasına bakın.
