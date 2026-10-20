# Teknik tasarım

## Katmanlar

| Dosya | Sorumluluk |
|---|---|
| `security.py` | Parola/PIN doğrulama ve yavaş tuzlu özet |
| `storage.py` | SQLite şeması, işlemler, işletim sistemi dosya kilidi, bütünlük |
| `service.py` | Kimlik doğrulama, yönetici yetkisi, çalışma/ücret/ödeme kuralları, saat şüphesi |
| `reports.py` | Gün sınırında bölme, kesirli hesap, bakiye ve CSV/XLSX |
| `backup.py` | SQLite anlık yedek, SHA-256, doğrulanan geri yükleme |
| `ui.py` | PySide6 kartlar, PIN tuş takımı, yönetici pencereleri |
| `__main__.py` | Başlatma, ilk kurulum, bakım komutları, hata/kurtarma akışı |

İş katmanı Qt’ye bağımlı değildir. `SystemClock` yerine kontrollü bir saat verilerek zaman
senaryoları test edilir. `pathlib` ve platforma göre veri yolu seçimi macOS taşınmasını kolaylaştırır.
Şimdiki Qt ekranları macOS üzerinde de çalıştırılıp test edildi; macOS imzalı `.app` dağıtımı yapılmadı.

## İşlem güvenliği

SQLite bağlantısı foreign key açık, `busy_timeout=10000`, `synchronous=FULL`,
`journal_mode=DELETE` ile açılır. Tek bilgisayarda uygulama düzeyinde işletim sistemi kilidi vardır.
Yönetici ve personel değişiklikleri `BEGIN IMMEDIATE` ile seri yazılır.

Bu MVP, tek yazıcı senaryosunda rollback journal kullanır. Açılışta SQLite’ın sıcak journal
kurtarmasına izin verilir, ardından bütünlük denetimi yapılır. Hatalı dosya sessizce silinmez
ve yeni veritabanıyla değiştirilmez.

Kayıt değişikliği, işlem geçmişi ve işlem kimliği aynı transaction içindedir.
Hata veya süreç sonlandırması commit öncesinde olursa birlikte geri alınırlar.
Disk/hardware arızasına karşı mutlak garanti verilmez; FULL senkronizasyon ve yedek birlikte kullanılır.

Kısmi unique index personel başına tek aktif açık kayıt zorlar. Bütünlük denetimindeki çakışma kontrolü,
personel başına başlangıca göre sıralı tarama (pencere fonksiyonu) ile O(n log n) çalışır. Uygulama ayrıca çakışan
zaman aralıklarını reddeder. İşlem UUID’si ve içerik parmak izi aynı isteğin tekrarını etkisizleştirir.
Çıkışta beklenen açık kayıt kimliği doğrulanır; eski ekran yeni kaydı kapatamaz.
Düzeltmelerde revision sayısı eski ekranın yeni değişiklik üzerine yazmasını engeller.
Ödeme için aynı kişi/tür/tutar/saniyede ikinci kayıt da reddedilir.

## Kimlik ve saat

Personel her giriş/çıkışta PIN girer; kalıcı personel oturumu yoktur.
Yönetici yetkisi bellekte rastgele bir token ile temsil edilir ve her korunan servis çağrısında kontrol edilir.
Beş dakika servis işlemi yapılmadığında token geçersiz olur. Ekran ayrıca beş dakika kullanıcı
etkileşimi olmayınca tüm yönetici alt pencerelerini kapatır.
PIN ekranı açıldıktan 60 saniye sonra kapanır. Başarılı/başarısız işlemde PIN alanı temizlenir.

Hatalı deneme sayısı ve kilit bitişi SQLite’ta tutulur; hata mesajı verilmeden önce commit edilir.
Kimlik doğrulama günlüklerinde şifre veya PIN bulunmaz. Dosya sisteminde hata günlükleri yetkisiz
kişilere açılmamalıdır.

Saat örnekleri ana ekranda 15 saniyede bir ve her personel işlemi öncesinde alınır.
İşletme saat dilimi sabittir; işletim sistemi saat dilimi değişse de rapor sınırları değişmez.
Kalıcı en son görülen saat, monotonik süre ve açılış aralığı karşılaştırılır.
Saat uyarısı (`meta.clock_alert`) kalıcıdır ancak işlemleri durdurmaz: uyarı sürerken açılan veya
kapanan her kayıt `sessions.review` alanına uyarı metnini alır. Yönetici düzeltmesi/iptali bu alanı temizler.
Uzun ara bildirimi (`meta.clock_notice`) yalnızca bilgidir. Onay iki durumu da temizler,
mevcut kayıt saatlerini ve inceleme işaretlerini değiştirmez.

## İş günü

`meta.day_start_hour` (varsayılan 5) iş gününün yerel başlangıç saatidir. Rapor gün/ay sınırları,
“Bugün/Bu ay” düğmeleri ve tablo filtreleri bu sınırı kullanır (`reports.business_day`, `Service.day_bounds`).
Her `tick()` (15 sn ve her personel işlemi) açık kayıtları tarar; iş günü sınırını geçmiş ve işaretsiz olanlara
`review` notu yazar, revision’ı artırır ve `SESSION_FLAG` audit kaydı ekler (eski düzeltme ekranı üzerine yazamaz).
Ayar değişikliği `SETTING_CHANGE` olarak denetlenir.

## Veri modeli

`employees`: aktif/arşiv, güncel ücret. `credentials`: personel ve yönetici özetleri, kilitler.
`rate_history`: her ücret değişikliğinin işlem zamanı ve yeni ücret.
`sessions`: giriş/çıkış, kayıt ücreti, iptal, revision ve inceleme notu (`review`).
`payments`: ödeme/avans ve iptal. `receipts`: tekrar işlem önleme.
`audit`: kim/ne zaman/ne yaptı, önce/sonra, gerekçe, önceki özet ve SHA-256.
`meta`: sabit saat dilimi, saat inceleme durumu, zaman sınırı.

Personel veya çalışma kaydı fiziksel olarak silinmez. İptal edilen kayıt rapora girmez,
denetim geçmişinde saklanır. Yönetici adı tekil `admin` olarak kaydedilir; ayrı çoklu yönetici
hesapları bu MVP’de yoktur. İşlem kodları geçmiş ekranında teknik İngilizce adlarıyla görünür.

## Bütünlük ve kurtarma

Bütünlük denetimi `PRAGMA integrity_check`, `foreign_key_check`, zaman çakışması,
personelin kimlik bilgisi varlığı, işlem zinciri ve son işlem görüntüsünün personel/çalışma/ödeme
kayıtlarıyla tutarlılığını kontrol eder. Bu kontroller açılışta, elle ve yeni yedek üzerinde uygulanır.

Şema sürümü 2’dir; sürüm 1 dosyaları açılmaz (gerçek veri öncesi değişiklik, migration yoktur).

Yedek doğrudan SQLite Backup API ile geçici dosyaya yazılır. Dosyalar yazılabilir tanıtıcıyla fsync edilir
(Windows `FlushFileBuffers` salt okunur tanıtıcıyı reddeder). Ana ekran günlük yedeği süreç başına bir kez
doğrular; her 15 saniyede dosyanın tamamı yeniden denetlenmez. Denetlenip fsync edildikten sonra
son adına taşınır; yanında SHA-256 dosyası üretilir. Var olan yedek üzerine yazılmaz.
Otomatik yedekler aynı diskte olduğundan disk kaybına karşı ayrı diskte bir kopya gerekir.

Kurtarma kaynak dosyayı, varsa checksum’ı ve yönetici şifresini doğrular. Mevcut dosya sağlamsa
onun şifresi, mevcut dosya bozuk/yoksa yedekteki yönetici şifresi gerekir.
Eski dosya/journal/WAL/SHM dosyaları zaman damgalı recovery klasörüne korunur.
Yeni dosya aynı diskte hazırlanır ve atomik dosya değiştirmesiyle kurulur.
Kurtarma işlemi audit’e eklenir ve açık kayıt/saat incelemesi zorunlu olur.
Kurtarma sırasında beklenmedik güç kesilmesinde recovery klasörünü koruyup doğrulanmış kaynak
yedekle işlemi tekrar uygulayın.

## Dışa aktarma

CSV UTF-8 BOM, noktalı virgül ayırıcı ve noktalı ondalık kullanır. Excel’in bölge ayarı farklıysa
CSV’yi “Veri → Metin/CSV” üzerinden uygun ayırıcı/ondalıkla içe aktarın; XLSX doğrudan sayısal
hücreler içerir. XLSX’te özet, günlük, giriş–çıkış, ödeme–avans ve açıklama sayfaları bulunur.

Personel adları ve notlar gibi dış girdiler `=`, `+`, `-`, `@` ile başlayan formül ifadelerinden
korunur. Rapor geçici dosyada hazırlanır, başarıyla bitince hedefi değiştirir.
Özet ve ayrıntılar aynı veritabanı transaction görüntüsünden hesaplanır.

## Başvurular

- [SQLite transaction ve rollback journal](https://www.sqlite.org/lockingv3.html)
- [SQLite Backup API](https://www.sqlite.org/backup.html)
- [SQLite bütünlük pragmaları](https://www.sqlite.org/pragma.html)
- [Python PBKDF2](https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac)
- [Qt for Python dağıtımı](https://doc.qt.io/qtforpython-6/deployment/index.html)
