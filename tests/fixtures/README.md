# Eski sürüm veri dosyaları

`sema-v2.sqlite3`: şema sürüm 2 ile `scripts/make_sample_db.py` tarafından üretildi
(yönetici kodu 3917, personel "Örnek Personel" PIN 4829; 1 kayıt, 1 avans).

Bu dosyalar **hiç değiştirilmez**. Her şema değişikliğinde, değişiklikten önce yeni bir
`sema-v<n>.sqlite3` eklenir; `tests/test_migrations.py` hepsinin güncel programla açılıp
yükseltildiğini ve verinin korunduğunu denetler.
