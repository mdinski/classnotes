# Mevcut Şematik Üzerinde JDO


Mevcut Şematik Üzerinde JDO



 Yıl 1997. CORBA, nesnesel tasarım kavramlarının  yükselişte olduğu yıllar. Müşteri-Servis adlı iki bacaklı mimarilerden oldukça hasat alınmış, üç bacaklı İnternet mimarilerinin eli kulağında. C++ kullanılıyor, ama herkes Java'yı şöyle yan gözle kontrol ediyor. Kimse artık nesnesinin içine SQL koymak istemiyor. Hâtta böyle görüşleri savunmak demode sayılıyor.               Bu ortamda takımımıza dahil olan bir arkadaş, POS adlı nesnesel-ilişkisel bağlaşım sağlayan, ve bizi kod içine SQL yazmaktan 'kurtaracak' bir ürün yazmaya girişti. Olay uzun sürdü. İş bitinceye kadar projemiz çok ilerlemişti. C++ dili tip sistemi programcıya gerekli bilgileri vermiyordu. Arkadaş çok zorlandı. POS'u kaldırıp attık. Fakat aynı tür problemler, her projede kulağımıza çalındı. Ah Java içine SQL yazmaktan kurtulsak!               Yıl 2003. Ne gariptir ki hâla bazı şirketlerde Java içine SQL konulduğunu görüyoruz. Amerika'da en son yardım ettiğimiz IFS adlı (piyasa durumu oldukça iyi olan) bir finans şirketinin BT mimarisini burada bütünü ile tarif etmeyelim, okuyan programcılar  ağlayabilir. Swing içinde depolu işlem (stored procedure) çağıran, depolu işlem içinde 'bu veri satırı acaba yeni mi değil mi?' gibi eğer koşulu işletip cevaba göre INSERT ya da UPDATE yapan kodlara bakarken, JDO'yu tepsiye koyup acilen servis yapmamız gerektiğini anladık.           SQL'a Hayır          Bilgi işlem programları %80 kadar kısmını özel bir satıra erişmek, bunu değiştirmek, geri koymak, ya da bazen silmek gibi sorunlarla geçirir. Bir veri tipinden, mesela Müşteri olsun, alakalı başka bir veri tipine, mesela Fatura'ya, atlanması gerekebilir. Bu gibi durumlarda JOIN yapılır. JDO en çabuk olarak al/ver/sil sorunlarını ve uzun vadede JOIN'leri bile ihya edebilecek bir çözüm platformu sâğlayacaktır. TEK BİR SQL KODU YAZMADAN.          Değişik JDO Kullanımları          Site kodları içinde gördüğünüz JDO kullanımı, ortada olmayan  bir tablo durumu öngörüyordu. Java nesnesinden Tablo çıkartmak ilginç bir kullanım gibi gelmiş olabilir, bu sayede CREATE TABLE bile yazmaktan kurtulmuş oluyorduk. Fakat bizim ufak projemiz için Java ile Tablo yazımı aynı anda başladı. Her zaman durum böyle olmayabilir. Hâtta, 'genelde' durum şöyle olacaktır: Ortada XYZ şematiği (tablolar sürüsü) var, ve sizin Java kodunuzun bu şematiğe erişip bilgi işlem hareketleri yapması gerekiyor. İşte bu gibi durumlar için JDO'yu nasıl kullanacağız, onu görelim.               İlk önce hangi JDO gerçekleştirimi kullanacağımıza karar vermemiz gerekiyor.              Ravaçta bedava JDO ürünleri olsa da, yeni ortaya çıkan bu standart için ufakta olsa ödeme yapmamız gereken (programcılar deneme lisansı rahatlıkla alabilir) bir JDO türü kullanacağız. Eğer şirketiniz JDO için para ödemeye hazır ise, iyi bir destek ve hata onarımları için KODO'yu seçebilirsiniz. Bu ürün ile kuvvetli bir JDO gerçekleştirimi, iyi destek ve her türlü veri tabanı desteği almış olacaksınız. Kendi sitemizde MySql, önceki işimizde Oracle, şimdikinde Sybase kullandığımız halde hepsinde KODO kullanma imkanımız oldu. Yeni bir ürünü baştan öğrenmemiz gerekmedi. Öğrenim eğrisi programcılık için çok önemlidir. Küpe.               Evet, KODO'yu kurun, KODO lib dizini altındaki .jar dosyalarının hepsini kendi projenizin geliştirme ağacı altındaki lib dizinine koyun. Artık yeni mimariler lazım olan dış JAR'ları bile KKİ'a (CVS gibi) kod ile beraber kayıt ediyorlar. Böylece bir toptan indirme ile lazım olan herşey gelmiş oluyor.               Şimdi örnek dosyaları indirin. Fatura nesnesini göreceksiniz. Fatura'yı, KODO'nun geri mühendislik özelliğini kullanarak, (bu sefer Java yazmaktan kurtularak) veri tabanından direk olarak çıkardık. Örnek build.xml'i kullanarak ant geri-muhendislik komutu verdiğinizde bütün veri tabanınızı Java nesneleri halinde çıkatmanız mümkün. Tabii yanda gelen .xml dosyalarını JDO ile kullanmak için biraz değiştirmeniz gerekecek. Örnek kodlar bu değiştirilmiş en son şekli kullanıyorlar.              Fatura nesnesinin çıktığı tablo şöyle kurulmuştu:               CREATE TABLE FATURABEGINFATURA_ID                  NUMERIC(10)BANKA_ISMI                 VARCHAR(20)......END              Şimdi Beanler.jdo ayartanım dosyasına bakalım. Bu dosya, Java nesnesi niteliklerini tablo kolonlarıyla eşliyor. JDO, bu dosyayayı kullanarak, makePersistent() komutu aldığında 'hangi kolona hangi niteliği' UPDATE ya da INSERT ile vermesi gerektiğini otomatik olarak anlıyor, ve işlemi gerçekleştiriyor.               Build.xml üzerinde jdo-sinif-genislet komutu, derleme yapıldıktan sonra ortaya çıkan .class dosyaları üzerinde işlem yapar. JDO'nun 'sihri' işte bu komutta: Sınıf genişletmek ile, class dosyaları içine JDBC kodları sokuşturuluyor. Evet doğru duydunuz. Beanler.jdo dosyasından gelen ayarlar, .class içine konulan JDBC, ve KODO kütüphanesinde bulunan destek kodların tümünü kapsayan JDO ile SQL yazmaktan kurtulmuş oluyoruz.                JDO ile, SQL'suz günler sizin olsun.          Kaynaklar          * KODO sitesinden JDO kütüphanesini, ve kullanım lisansını alabilirsiniz.   * Yazımızda bahsedilen örnek kodlar.   * Otomatik derleme, test etme gibi işlemler için Ant vazgeçilmez bir araç.   * Bedava bir JDO paketi için TJDO hakkındaki yazımızı okuyabilirsiniz.



