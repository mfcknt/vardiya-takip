# Kararlar ve nedenleri

Programı yıllar sonra devralacak kişi için: neden böyle yapıldığı. Bu kararlar işletme sahibiyle
konuşularak verildi; değiştirmeden önce onunla konuşun.

## Kimlik ve kodlar

| Karar | Neden |
|---|---|
| Personel PIN’i **ve** yönetici şifresi 4 rakam | Kiosk dokunmatik; uzun şifre ekran klavyesi ister ve unutulur. Kademeli kilit tahmini aylar sürdürür. |
| 1111, 1234/4321, 1212, 1122 reddedilir | En çok denenen kodlar. |
| Aynı kod birden çok kişide olabilir | “Bu kod kullanılıyor” mesajı başkasının kodunu ele verirdi. Hiçbir mesaj başkasının kodu hakkında bilgi vermez. |
| Personel kilidi 30 sn → 5 dk; yönetici 5 → 15 → 30 dk → 1 saat | Personel işe geç kalmasın; yönetici paneli korunsun. Kilit yeniden başlatmada sürer. |
| Unutulan yönetici şifresi: kâğıtta 20 rakamlık kurtarma anahtarı | Başka sıfırlama yolu “arka kapı” olurdu. Rakam olması kiosk tuş takımıyla girilebilsin diye; tek kullanımlık, kullanılınca yenisi gösterilir. |
| Şifre/PIN alanları hiçbir zaman odak almaz | Windows dokunmatik klavyesi açılıp ekranı kapatmasın; uygulamanın kendi tuş takımı var. |

## Zaman ve kayıt

| Karar | Neden |
|---|---|
| İş günü 05:00’da başlar (0–12 arası ayarlanır) | Kafe 09:00’da açılır, ~01:00’de kapanır; gece yarısını geçen vardiya o güne yazılmalı. |
| Sınırı geçen açık kayıt “çıkış unutuldu” olur; program çıkış saati **uydurmaz** | Uydurulan saat ya personeli ya işletmeyi haksız yere etkiler; gerçek saati yönetici girer. |
| Saat uyarıları personeli durdurmaz, kaydı incelemeye işaretler | Saat bozuk diye kimse işe başlayamamalı; sorun yöneticinin önüne gelir. |
| Kayıt ve personel silinmez; iptal edilir | Her değişiklik zincirleme özetli işlem geçmişinde iz bırakır; sonradan anlaşmazlıkta kanıt olur. |
| İşe girişte geçerli ücret kaydın tamamına sabitlenir | Ücret değişikliği geçmişi ve açık kaydı değiştirmez. |
| Para kuruş cinsinden tam sayı; hesap kesirli (Fraction) | Yuvarlama kayması ve büyük tutarlarda taşma olmaz. |
| Ay kapatılınca o ay ve öncesi değiştirilemez | Ödenmiş ay sonradan sessizce değişmesin. Yeniden açma şifre ve gerekçe ister, iz bırakır. |
| Personel kioskta yalnız kendi gün/saatini görür, para görmez | Kiosk ekranı herkesin önünde; tutar özel bilgidir. Ekran 30 sn’de kapanır. |

## Veri ve dayanıklılık

| Karar | Neden |
|---|---|
| Tamamen çevrimdışı, tek bilgisayar, SQLite | İnternet kesintisi işi durdurmaz; sunucu ve aylık ücret yok. |
| Her yedek doğrulanır; otomatik yedekler sınırlı tutulur, elle alınanlar silinmez | Bozuk yedek, yedeksizlikten tehlikelidir. |
| Şema değişikliği: eski dosya kopyada yükseltilir, doğrulanır, eski dosya saklanır | Güncelleme veriyi bozamaz; yarıda kalan güncelleme dosyaya dokunmaz. |
| Daha yeni sürümün dosyasını eski program açmaz | Geri dönülen eski program yeni alanları bilmeden veriyi bozmasın. |
| `tzdata`, Windows imajı ve CI eylemleri sabit sürümde | Yıllar sonra aynı kaynaktan aynı program derlensin. Saat dilimi verisi eskiyince CI uyarır. |
| Kurulum dosyaları ve kaynak kod GitHub dışında arşivlenir (`scripts/arsivle.py`) | GitHub hesabı veya servis değişirse elde kurulabilir ve derlenebilir bir sürüm kalsın. |

## Görünüm

| Karar | Neden |
|---|---|
| Logo rengi bordo `#3a0300` ve krem; Jost ve Quicksand programla gelir | İşletmenin kimliği; yazı tipleri bilgisayara kurulu olmasa da aynı görünsün. |
| Her kişi ince bir “Ó” halkası | Logodaki harf; içeride/dışarıda/unutuldu/kilitli tek bakışta anlaşılır. |
| Süsleme amaçlı marka cümlesi yok | Sahibinin isteği: ekranlar yalnızca bilgi gösterir. |
| Kiosk uyarısı yalnızca “Yönetici için N not var.” | Personelin yapamayacağı işleri ayrıntılı göstermek kafa karıştırır; ayrıntı yönetici panelinde. |
| Küçük dizüstü ekranına sığar (1024 px) | Kafedeki bilgisayar küçük olabilir; yana kaydırma test edilir. |

## Bilerek yapılmayanlar

- **Makine dışı otomatik yedek** (USB/bulut): sona bırakıldı; şimdilik yedekleri elle başka diske kopyalayın.
- **Kod imzalama:** ücretli sertifika gerekir; o zamana kadar Windows “bilinmeyen yayıncı” uyarısı çıkar.
- **Ayrılan personelin verisinin silinmesi:** yasal saklama süresi mali müşavirle netleşince eklenecek.
