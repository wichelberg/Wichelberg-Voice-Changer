# Wichelberg Voice Changer

Sesini seçtiğin sese çevirip Discord ve FiveM'e aktaran program (Windows 10/11).

> **Gerçek kişilerin sesleri sadece kendi izinleriyle kullanılabilir.** Başkasının sesini izinsiz taklit etmek yasak.

---

## 1. İndir ve aç
1. Sağdaki **Releases** bölümünden en yeni `Wichelberg-x.y.z.zip` dosyasını indir.
2. Zip'e sağ tıkla → **Tümünü ayıkla…** → **Belgeler** veya **Masaüstü** gibi bir yer seç.
   - Zip'in içinden çalıştırma; önce mutlaka çıkar.
   - *Program Files* içine koyma.
3. Çıkan **Wichelberg** klasöründe **Wichelberg.exe**'ye çift tıkla.

### "Windows bilgisayarınızı korudu" uyarısı
Program imzasız olduğu için Windows ilk seferde uyarabilir: **Ek bilgi** → **Yine de çalıştır**.
Antivirüs program dosyasını yanlışlıkla şüpheli bulursa, programı sana gönderen kişiye sor.

### İlk açılış (bir kez, ~5-10 dakika)
Kurulum ekranı açılır ve gerekenleri tek tek indirir (~530 MB). Her şey **sadece Wichelberg klasörünün içine**
iner; bilgisayarına başka hiçbir şey kurulmaz. Bittiğinde **Programı aç**'a bas. Sonraki açılışlarda program
doğrudan açılır.

Klasörde sadece `Wichelberg.exe` görünür; programın dosyaları gizli `_wichelberg` klasöründedir. **Onu silme.**

---

## 2. VB-Cable (bir kez)
Sesin Discord'a gitmesi için ücretsiz sanal kablo gerekir. Program kurulu olup olmadığını kendisi kontrol eder.
1. https://vb-audio.com/Cable/ → **VBCABLE_Driver_Pack** zip'ini indir, çıkar.
2. `VBCABLE_Setup_x64.exe` → sağ tık → **Yönetici olarak çalıştır** → **Install Driver**.
3. **Bilgisayarı yeniden başlat.**

Windows'un varsayılan hoparlörünü CABLE Input **yapma**; yoksa bilgisayarın bütün sesi Discord'a gider.

---

## 3. Ses ekle
Program içinde ses gelmez; sesler sana ayrıca (.zip olarak) gönderilir.
1. Programda **Ses Kütüphanesi** sekmesine geç.
2. Sana gönderilen zip'i listeye **sürükle** (veya **İçe aktar…**). Zip'i açmana gerek yok.
3. AI modunu ilk kez kullanmadan önce aynı sekmede **Hız testini başlat**'a bas (~5 dakika; oyun kapalıyken).
   Bilgisayarının AI modunu oyunla birlikte kaldırıp kaldırmadığını ölçer. Harici ekran kartı önerilir.

---

## 4. Kullan
1. **Ana ekran** → Mikrofon: kendi mikrofonun. Discord'a çıkış: **CABLE Input** (kendiliğinden seçilir).
2. **Ses** kartında mod seç: **AI** (gönderilen sesler), **DSP** (hafif, her bilgisayarda çalışır) veya **Normal ses**.
3. **▶ Başlat**.
4. **Ctrl+F7** dönüştürmeyi açar/kapatır (oyunun içindeyken de çalışır). Kapalıyken normal sesin gider.

**Discord:** Ayarlar → Ses ve Görüntü → Giriş Aygıtı: **CABLE Output**. Gürültü Azaltma'yı ve Yankı Engelleme'yi kapat.
**FiveM:** Ayarlar → Ses → Mikrofon: **CABLE Output**.

Sağ üstteki **Gelişmiş görünüm** ayrıntılı ayarları açar; **Koyu/Açık tema** düğmesi görünümü değiştirir.

---

## 5. Güncelleme
Yeni sürümün zip'ini indir ve **aynı yere** çıkar; "dosyaların üzerine yaz" de. Seslerin ve ayarların korunur.
Gerekirse program açılışta değişen parçaları kendisi indirir.

## 6. Sorun olursa
- Program açılmazsa başlatıcı hatayı gösterir: **Onar** kurulumu baştan yapar (sesler ve ayarlar korunur).
- Çökme veya hata anında Discord'a **sessizlik** gider; gerçek sesin istemeden duyulmaz.
- Hata yazısını veya `_wichelberg\data\logs\program.log` dosyasını programı sana gönderen kişiye ilet.
