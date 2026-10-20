# Windows kurulumu ve dağıtım

Hedef: Windows 10/11 x64, yerel disk, tek kullanıcı hesabı, Python 3.12 ile derleme.
Gerçek dokunmatik cihaz ve Windows `.exe` doğrulaması teslim ortamında yapılamadı.
Bu adımlar ve Windows CI iş akışı o doğrulamayı yapılabilir hâle getirir.

## Kaynaktan kullanım

1. Python 3.12 x64 ve Python Launcher (`py`) kurun.
2. Projeyi yerel bir klasöre çıkarın. `Kurulum.cmd` dosyasını çalıştırın.
3. Testler geçtikten sonra `Baslat.cmd` ile açın.
4. Şifreyi belirleyip gerçek kullanımdan önce deneme personeliyle giriş/çıkış ve yedek/kurtarma yapın.

Bağımlılıkların ilk indirilmesi internet gerektirir. Uygulama kendisi ağ bağlantısı kullanmaz.
Son kullanıcıda Python istemiyorsanız aşağıdaki paketleme adımını uygulayın.

## Windows EXE üretimi

Proje kökünde PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

Bu komuttaki execution policy seçimi yalnızca açılan PowerShell süreci içindir.
Betik bağımlılıkları kurar, tüm testleri çalıştırır, PyInstaller ile klasör paketi üretir,
belgeleri ve kurulu paketlerin lisans dosyalarını ekler, ZIP oluşturur.

Çıktı: `dist\VardiyaTakip-Windows-x64.zip`.

ZIP içindeki **VardiyaTakip klasörünün tamamını** hedef bilgisayara taşıyın:

- `VardiyaTakip.exe`: normal grafik arayüz.
- `VardiyaBakim.exe`: konsollu bakım aracı.
- `_internal`: Python, Qt ve diğer çalışma bağımlılıkları; silmeyin.
- `docs`, `README.md`, `THIRD_PARTY`: kullanım ve dağıtım bilgileri.

Bakım örneği:

```powershell
.\VardiyaBakim.exe --check
.\VardiyaBakim.exe --restore "D:\Yedekler\vardiya.sqlite3"
```

Paketleme Windows üzerinde yapılmalıdır. PyInstaller çıktısı derlendiği işletim sistemi ve
mimariye özeldir; macOS üzerinde Windows EXE üretmez.
[PyInstaller dağıtım modeli](https://pyinstaller.org/en/stable/operating-mode.html).

GitHub deposuna konulduğunda `.github/workflows/windows.yml`, Windows üzerinde test ve paketleme
yapar; ZIP’i iş akışının artifact bölümüne ekler. Bu teslimde iş akışı uzak bir depoda çalıştırılmadı.

## İnternetsiz kurulum hazırlama

İnternete bağlı Windows x64 / Python 3.12 bilgisayarda:

```powershell
py -3.12 -m pip wheel --wheel-dir wheelhouse .
```

Proje ile `wheelhouse` klasörünü hedefe taşıyın:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse vardiya-takip
.\.venv\Scripts\python.exe -m vardiya
```

Bu işlem projenin ve bağımlılıklarının kurulabilir wheel dosyalarını hazırlar.
macOS wheel dosyalarını Windows’a taşımayın.
Son kullanıcı için EXE klasör paketi daha az kurulum adımı gerektirir.

## Hedef bilgisayar kabul kontrolü

- İnternet kapalıyken uygulamayı açın; kurulum şifresini, personeli ve PIN’i doğrulayın.
- Fare, fiziksel klavye, Enter, dokunarak PIN ve kaydırma hareketlerini deneyin.
- %100, %125, %150 ölçeklerde tüm düğmelere erişilebildiğini kontrol edin.
- Bir giriş kaydedin; Görev Yöneticisi ile kapatıp açın. Açık kayıt korunmalı.
- Aynı işlemi hızlı çift tıklayın; tek kayıt oluşmalı.
- Sistem saatini değiştirerek şüphe uyarısını, yönetici kontrolünü ve geçmiş kaydını doğrulayın.
- Gece yarısı ve ay sonu için yöneticiyle deneme kayıtları oluşturup raporu karşılaştırın.
- Excel/CSV dosyasını hedef Excel sürümünde açın.
- Haricî diske yedek alın, ayrı bir deneme klasörüne kurtarın, bütünlük denetimini çalıştırın.
- Disk doluluğu, yazma izni ve UPS/elektrik kesintisi koşullarını gerçek donanımda değerlendirin.

Programı normal Windows hesabıyla açın. Verilerin bulunduğu kullanıcı hesabını değiştirmeyin.
Yeni sürüm yüklemeden önce yönetici panelinden yedek alın. Bu sürüm yalnızca şema sürümü 2’yi açar;
gelecekteki şema yükseltmeleri için ayrıca migration ve geri dönüş planı gerekir.

## Lisanslar

Qt/PySide6, Python ve diğer üçüncü taraf bileşenlerin lisans metinlerini dağıtımda koruyun.
Paketleme betiği kurulu paketlerden bulunan lisans dosyalarını toplar; ürünün nihai dağıtım
modeli için ilgili Qt lisans şartlarını ayrıca uygulayın.
[Qt for Python dağıtımı](https://doc.qt.io/qtforpython-6/deployment/index.html).
