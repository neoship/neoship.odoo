"use strict";

// Coordinates refer to the untouched 1440 × 1000 captures. Labels live outside
// the images so they stay legible on small screens and can be translated.
(() => {
  const mark = (box, pin, en, sk) => ({ box, pin, en, sk });
  const guides = {
    "04-carriers.webp": [
      mark([955, 552, 60, 31], [1070, 568], "Click Select on the SPS row for the first walkthrough.", "Pre prvý príklad kliknite na Select v riadku SPS."),
      mark([955, 512, 60, 31], [1028, 466], "Select Packeta here; home delivery then opens a second, country-specific picker.", "Tu vyberte Packetu; doručenie na adresu potom otvorí druhý výber podľa krajiny."),
      mark([841, 346, 117, 285], [900, 686], "Pickup Points indicates that the carrier supports pickup points.", "Pickup Points znamená, že dopravca podporuje výdajné miesta."),
    ],
    "06-order.webp": [
      mark([664, 50, 112, 41], [831, 70], "After confirming, open the delivery from the Delivery smart button.", "Po potvrdení otvorte dodací list tlačidlom Doručenie (Delivery)."),
    ],
    "06-shipping-wizard.webp": [
      mark([382, 436, 326, 34], [763, 453], "Choose the Neoship delivery method.", "Vyberte dopravnú metódu Neoship."),
      mark([607, 514, 101, 31], [763, 530], "Click Get rate: the Fixed Price of the method appears as Cost.", "Kliknite na Get rate: ako Cost sa zobrazí Fixed Price metódy."),
      mark([382, 515, 228, 29], [540, 597], "Check the cost before adding the line. 0.00 means the rate was not fetched.", "Pred pridaním riadka skontrolujte cenu. 0,00 znamená, že cena sa nenačítala."),
      mark([242, 590, 56, 41], [329, 664], "Add puts the delivery line on the order.", "Add pridá riadok dopravy do objednávky."),
    ],
    "07-ready.webp": [
      mark([184, 508, 263, 34], [447, 576], "Check the delivery method: Kuriér SPS.", "Skontrolujte dopravnú metódu: Kuriér SPS."),
      mark([184, 620, 197, 34], [436, 637], "Weight for shipping is the packed weight sent to the carrier; it starts from the product weights.", "Hmotnosť na prepravu (Weight for shipping) sa posiela dopravcovi; predvyplní sa z hmotností produktov."),
      mark([12, 109, 83, 41], [29, 202], "Validate creates the Neoship shipment and downloads the label.", "Validate vytvorí zásielku v Neoship a stiahne štítok."),
    ],
    "09-sps-created.webp": [
      mark([822, 109, 84, 41], [864, 205], "Done confirms the warehouse transfer, not delivery to the customer.", "Hotovo (Done) potvrdzuje skladový presun, nie doručenie zákazníkovi."),
      mark([954, 264, 474, 71], [1397, 363], "The chatter records the carrier, the tracking number and the delivery charge.", "História komunikácie zaznamená dopravcu, sledovacie číslo a cenu dopravy."),
      mark([955, 377, 188, 146], [1198, 450], "Open the PDF attachment in the chatter to view and print the label.", "Otvorte PDF prílohu v histórii komunikácie a zobrazte alebo vytlačte štítok."),
      mark([132, 342, 136, 47], [307, 405], "Additional Info opens the shipment details shown in the next image.", "Ďalšie informácie (Additional Info) otvoria údaje zásielky na nasledujúcom obrázku."),
    ],
    "10-tracking.webp": [
      mark([184, 498, 182, 34], [421, 515], "The tracking number returned by the carrier.", "Sledovacie číslo, ktoré vrátil dopravca."),
      mark([637, 466, 88, 59], [780, 496], "Read the carrier status here; Exported is separate from Odoo Done.", "Tu čítajte stav dopravcu; Exportovaná (Exported) je iný stav než Hotovo (Done) v Odoo."),
      mark([29, 709, 231, 46], [315, 732], "Each Neoship parcel of the transfer has its own row with tracking number, box and status.", "Každý balík Neoship dodacieho listu má vlastný riadok so sledovacím číslom, škatuľou a stavom."),
      mark([342, 709, 110, 46], [492, 771], "Check the actual transmitted COD amount here: 40.60 €.", "Tu skontrolujte skutočne odoslanú dobierku: 40,60 €."),
      mark([471, 587, 195, 41], [721, 608], "Download Label Again fetches the same shipment's PDF.", "Download Label Again znova stiahne PDF tej istej zásielky."),
      mark([471, 628, 157, 41], [678, 668], "Update Tracking refreshes the status immediately.", "Update Tracking ihneď obnoví stav zásielky."),
    ],
    "11-sps-label.webp": [
      mark([789, 545, 278, 193], [1122, 642], "Check the recipient against the actual box before attaching the label.", "Pred nalepením štítku skontrolujte príjemcu podľa skutočného balíka."),
      mark([789, 734, 344, 63], [1188, 766], "SPS marks the service: express, cash on delivery, phone notification.", "SPS označuje službu: expres, dobierka, telefonické avízo."),
      mark([789, 840, 221, 41], [1065, 860], "The reference is the Odoo transfer: BA/OUT/00006.", "Referencia je dodací list v Odoo: BA/OUT/00006."),
    ],
    "12-order-shipments.webp": [
      mark([234, 142, 312, 48], [601, 166], "The tracking number of the shipment.", "Sledovacie číslo zásielky."),
      mark([937, 142, 163, 48], [1137, 206], "Read the delivery group here, separately from the warehouse state.", "Tu čítajte skupinu stavu doručenia, osobitne od skladového stavu."),
      mark([663, 142, 111, 48], [814, 206], "The COD amount actually sent to Neoship.", "Suma dobierky, ktorá sa skutočne poslala do Neoship."),
      mark([1097, 150, 76, 31], [1103, 68], "Label opens this shipment's PDF.", "Štítok (Label) otvorí PDF tejto zásielky."),
      mark([1169, 150, 97, 31], [1321, 166], "Tracking opens the shipment's tracking page.", "Sledovanie (Tracking) otvorí stránku sledovania zásielky."),
    ],
    "13-cancel-shipment.webp": [
      mark([132, 342, 136, 47], [307, 405], "Open Additional Info on the delivery.", "Na dodacom liste otvorte Additional Info."),
      mark([184, 529, 94, 41], [333, 550], "This Cancel, beside Tracking Reference, cancels the carrier shipment.", "Toto Cancel vedľa Tracking Reference stornuje zásielku u dopravcu."),
      mark([45, 677, 837, 67], [937, 710], "After successful cancellation, the parcel rows and the tracking number are removed.", "Po úspešnom storne sa riadky balíkov aj sledovacie číslo odstránia."),
    ],
    "14-packeta-cz-config.webp": [
      mark([239, 502, 176, 39], [474, 522], "The Packeta settings are inside Neoship Configuration.", "Nastavenia Packety sú v záložke Neoship Configuration."),
      mark([878, 623, 57, 24], [990, 635], "Choose Packeta as the main Neoship Carrier.", "Ako hlavný Neoship Carrier vyberte Packetu."),
      mark([1271, 710, 100, 31], [1412, 761], "The second Choose button selects Packeta's home-delivery service.", "Druhé tlačidlo Choose vyberá službu Packety pre doručenie na adresu."),
      mark([878, 767, 103, 24], [1036, 779], "Confirm the stored home-delivery country matches the recipient.", "Overte, že uložená krajina doručenia na adresu zodpovedá príjemcovi."),
      mark([1199, 821, 172, 31], [1300, 785], "Load Packeta Sizes creates a package type for each Packeta size.", "Load Packeta Sizes vytvorí typ balíka pre každú veľkosť Packety."),
      mark([1022, 51, 404, 64], [960, 150], "The notification says how many package types are ready.", "Hlásenie ukáže, koľko typov balíkov je pripravených."),
      mark([878, 822, 200, 30], [960, 885], "Default Package Type: the size for parcels without one; empty means the carrier's largest size.", "Default Package Type: veľkosť pre balíky bez typu; prázdne pole znamená najväčšiu veľkosť dopravcu."),
    ],
    "51-package-types.webp": [
      mark([347, 302, 200, 128], [447, 560], "The loaded InPost Paczkomaty Box sizes.", "Načítané veľkosti InPost Paczkomaty Box."),
      mark([1113, 302, 52, 128], [1190, 560], "Carrier Code is the size sent to Neoship.", "Carrier Code je veľkosť, ktorá ide do Neoshipu."),
      mark([65, 426, 450, 40], [200, 560], "Your own box stays without a carrier integration.", "Vlastná škatuľa zostáva bez integrácie dopravcu."),
    ],
    "15-packeta-country-picker.webp": [
      mark([243, 183, 954, 48], [1252, 207], "For a Czech address, check the CZ service, Czech Republic and CZK on this row.", "Pre českú adresu skontrolujte v tomto riadku službu CZ, Czech Republic a CZK."),
      mark([243, 783, 954, 48], [1252, 807], "For a Slovak address, choose the SK Packeta Home row instead.", "Pre slovenskú adresu namiesto toho vyberte riadok SK Packeta Home."),
      mark([1044, 792, 60, 31], [1104, 905], "Click Select on the matching home-delivery service.", "Kliknite na Select pri správnej službe doručenia na adresu."),
    ],
    "21-partial-cod.webp": [
      mark([660, 188, 112, 32], [716, 275], "The first delivery collects its 3 bags of coffee and the shipping: 108.60 €.", "Prvá dodávka vyberie svoje 3 balíčky kávy a dopravu: 108,60 €."),
      mark([660, 148, 112, 32], [605, 164], "The delivery completing the order collects the rest: 104.70 €. Together 213.30 €, the order total.", "Dodávka, ktorá objednávku dokončí, vyberie zvyšok: 104,70 €. Spolu 213,30 €, teda celá suma objednávky."),
      mark([36, 148, 207, 72], [140, 275], "One parcel per delivery of order S00014.", "Jeden balík na každú dodávku objednávky S00014."),
    ],
    "22-manual-cod.webp": [
      mark([132, 342, 136, 47], [307, 405], "Open the transfer's Additional Info tab.", "Otvorte na dodacom liste záložku Additional Info."),
      mark([637, 464, 29, 29], [721, 478], "Tick Manual Cash on Delivery only to override the computed amount, for example after a partial prepayment.", "Manual Cash on Delivery zaškrtnite, len ak chcete prepísať vypočítanú sumu, napríklad po čiastočnej platbe vopred."),
      mark([637, 519, 56, 34], [748, 536], "This amount is sent instead; 0.00 means no cash on delivery for this transfer.", "Namiesto vypočítanej sumy sa odošle táto; 0,00 znamená, že tento dodací list je bez dobierky."),
    ],
    "24-closure-schedule.webp": [
      mark([29, 167, 1342, 45], [1401, 210], "Read the account-wide warning: packages created outside Odoo are included too.", "Prečítajte upozornenie na celý účet: zahrnuté sú aj balíky vytvorené mimo Odoo."),
      mark([164, 293, 43, 29], [262, 308], "Leave Active switched off until the collection arrangement is approved.", "Active nechajte vypnuté, kým nie je schválený dohodnutý zvoz."),
      mark([791, 220, 580, 242], [1414, 387], "Review collection time, weekdays and the Europe/Bratislava timezone together.", "Spolu skontrolujte čas zvozu, dni a časové pásmo Europe/Bratislava."),
      mark([12, 109, 98, 41], [165, 130], "Close Now is account-wide; do not run it on a shared account without approval.", "Close Now je operácia pre celý účet; na zdieľanom účte ju nespúšťajte bez súhlasu."),
      mark([664, 50, 112, 41], [831, 70], "Protocols opens the results for this schedule.", "Protokoly (Protocols) otvoria výsledky tohto plánu."),
    ],
    "26-packeta-pickup-label.webp": [
      mark([608, 515, 388, 85], [978, 626], "The destination is the Z-BOX pickup point in Žilina, not the customer address.", "Cieľom je Z-BOX v Žiline, nie adresa zákazníčky."),
      mark([526, 799, 193, 67], [698, 909], "The routing strip contains pickup-point ID 19407.", "Smerovací pruh obsahuje ID výdajného miesta 19407."),
      mark([937, 799, 115, 67], [1051, 909], "COD: the 94.50 € cash on delivery is collected at the pickup point.", "COD: dobierka 94,50 € sa vyberie na výdajnom mieste."),
    ],
    "27-overweight-error.webp": [
      mark([163, 473, 1114, 61], [1332, 504], "Neoship refuses the data: 15.75 kg exceeds Packeta's 15 kg limit, and nothing is created.", "Neoship údaje odmietne: 15,75 kg prekračuje limit Packety 15 kg a nič sa nevytvorí."),
      mark([178, 526, 66, 41], [296, 566], "Close, then split the goods into boxes of at most 15 kg (or correct Weight for shipping) and validate again.", "Zavrite správu, rozdeľte tovar do balíkov s najviac 15 kg (alebo opravte Weight for shipping) a validujte znova."),
    ],
    "28-tracking-filters.webp": [
      mark([918, 50, 38, 43], [1011, 72], "Open the search options in Inventory → Operations → Deliveries.", "Otvorte možnosti vyhľadávania v Inventory → Operations → Deliveries."),
      mark([310, 553, 194, 108], [559, 607], "Neoship filters select transfers by carrier delivery status (New, Exported, In Transit, Delivered…), not by stock state.", "Filtre Neoship vyberajú presuny podľa stavu doručenia u dopravcu (New, Exported, In Transit, Delivered…), nie podľa skladového stavu."),
      mark([310, 662, 194, 57], [559, 690], "Not Delivered and Returned find delivery problems.", "Not Delivered a Returned nájdu problémy s doručením."),
      mark([540, 307, 135, 27], [730, 320], "Group By → Neoship Delivery groups transfers by carrier delivery status.", "Group By → Neoship Delivery zoskupí presuny podľa stavu doručenia u dopravcu."),
    ],
    "29-two-box-label.webp": [
      mark([883, 631, 71, 27], [982, 693], "The lower label is box 1 of 2.", "Dolný štítok je balík 1 z 2."),
      mark([883, 165, 71, 27], [1009, 178], "The upper label is box 2 of 2, with its own tracking number. Print both and attach one to each box.", "Horný štítok je balík 2 z 2 s vlastným sledovacím číslom. Vytlačte oba a na každú škatuľu nalepte jeden."),
    ],
    "30-cancelled.webp": [
      mark([954, 174, 290, 29], [1299, 188], "Verify the shipment-cancelled note in the chatter.", "V histórii komunikácie overte poznámku o storne zásielky."),
      mark([955, 377, 188, 146], [1198, 450], "The historical PDFs stay attached; do not reuse a cancelled label.", "Historické PDF zostávajú priložené; stornovaný štítok nepoužívajte znova."),
      mark([822, 109, 84, 41], [864, 205], "Done remains: cancelling shipping does not undo a stock move.", "Hotovo (Done) zostáva: storno prepravy nezvráti skladový pohyb."),
      mark([184, 498, 197, 34], [436, 515], "The old tracking reference is now empty.", "Pôvodné sledovacie číslo je teraz prázdne."),
      mark([140, 109, 131, 41], [326, 130], "Send to Shipper creates a new shipment for the same transfer if you need one.", "Send to Shipper vytvorí pre ten istý dodací list novú zásielku, ak ju potrebujete."),
    ],
    "31-sps-configuration.webp": [
      mark([534, 50, 126, 41], [656, 136], "Keep Test Environment selected while learning.", "Pri skúšaní ponechajte Testovacie prostredie (Test Environment)."),
      mark([167, 202, 83, 34], [305, 219], "Provider must be Neoship.", "Poskytovateľ (Provider) musí byť Neoship."),
      mark([167, 312, 219, 55], [441, 340], "Integration Level stays Get Rate and Create Shipment, so validating a delivery creates the shipment.", "Úroveň integrácie (Integration Level) ponechajte Get Rate and Create Shipment, aby validácia dodacieho listu vytvorila zásielku."),
      mark([878, 202, 119, 34], [1052, 219], "Fixed Price is the delivery charge added to orders; it is not a Neoship tariff quote.", "Fixed Price je cena dopravy pridávaná do objednávok; nie je to cenník Neoship."),
      mark([235, 498, 184, 47], [474, 522], "Open the Neoship Configuration tab. Account credentials are directly below.", "Otvorte záložku Neoship Configuration. Prihlasovacie údaje sú hneď pod ňou."),
      mark([29, 698, 156, 41], [240, 718], "Click Test Connection and check the green result.", "Kliknite na Test Connection a skontrolujte zelený výsledok."),
      mark([1271, 620, 100, 31], [1412, 671], "Choose beside Neoship Carrier opens the carrier picker.", "Choose pri Neoship Carrier otvorí výber dopravcu."),
      mark([878, 655, 56, 34], [989, 672], "Neoship Default Weight is the fallback in kilograms when the delivery has no weight.", "Neoship Default Weight je náhradná hmotnosť v kilogramoch, keď dodací list nemá hmotnosť."),
      mark([195, 815, 217, 89], [460, 854], "Edit Domain sets the Neoship COD rule: here, orders tagged Dobierka. The standard Cash on Delivery checkbox above is different.", "Edit Domain nastavuje pravidlo dobierky Neoship: tu objednávky so štítkom Dobierka. Štandardné políčko Cash on Delivery vyššie je iné nastavenie."),
      mark([1271, 710, 100, 31], [1412, 760], "Choose beside Label Format opens the label formats Neoship offers for the carrier.", "Choose pri Label Format otvorí formáty štítkov, ktoré Neoship pre dopravcu ponúka."),
    ],
    "50-label-format.webp": [
      mark([964, 473, 60, 31], [1100, 488], "Click Select on the format your printer uses.", "Kliknite na Select pri formáte, na ktorý tlačí vaša tlačiareň."),
      mark([255, 432, 172, 108], [470, 590], "The formats come from Neoship and differ per carrier.", "Formáty poskytuje Neoship a pre každého dopravcu sú iné."),
    ],
    "35-settings-menu.webp": [
      mark([43, -4, 91, 54], [115, 102], "Start in the Inventory app.", "Začnite v aplikácii Inventár (Inventory)."),
      mark([454, -4, 115, 54], [591, 81], "Open Configuration in the top menu.", "V hornom menu otvorte Konfigurácia (Configuration)."),
      mark([455, 261, 229, 35], [739, 278], "Under the Delivery heading, choose Delivery Methods. Delivery itself is not another button.", "Pod nadpisom Doručenie (Delivery) vyberte Dopravné metódy (Delivery Methods). Delivery nie je ďalšie tlačidlo."),
      mark([12, 51, 59, 41], [42, 147], "On the resulting list, click New to create a method.", "V otvorenom zozname kliknite na Nový (New) a vytvorte metódu."),
      mark([455, 288, 229, 62], [733, 341], "Closure Schedules and Protocols are in the same Delivery group; see chapter 10 before using them.", "Plánované uzávierky (Closure Schedules) a Protokoly (Protocols) sú v tej istej skupine Delivery; pred použitím si prečítajte kapitolu 10."),
    ],
    "36-pickup-point-field.webp": [
      mark([139, 199, 100, 39], [298, 218], "Open Other Info on the sales order.", "Na predajnej objednávke otvorte Ďalšie informácie (Other Info)."),
      mark([29, 890, 231, 50], [315, 915], "Neoship Pickup Point ID: the carrier-facing ID 19407, not the internal Neoship row ID 40283.", "Neoship Pickup Point ID: ID dopravcu 19407, nie interné ID riadka v Neoship 40283."),
      mark([29, 945, 231, 50], [315, 970], "Neoship Pickup Point Carrier ID stays 0 for Packeta's own points; partner carriers need their Packeta ID.", "Neoship Pickup Point Carrier ID zostáva 0 pri vlastných miestach Packety; partnerskí dopravcovia potrebujú svoje ID v Packete."),
    ],
    "52-put-in-pack.webp": [
      mark([511, 454, 521, 34], [1110, 470], "Package Type offers only sizes that fit the delivery's Packeta carrier.", "Package Type ponúkne len veľkosti, ktoré sedia na dopravcu Packety z dodacieho listu."),
      mark([514, 491, 380, 85], [1110, 532], "InPost Box A, B and C for the InPost locker.", "InPost Box A, B a C pre box InPost."),
      mark([514, 572, 380, 31], [1110, 600], "Your own boxes without a carrier integration are offered too.", "Ponúknu sa aj vlastné škatule bez integrácie dopravcu."),
    ],
    "37-closure-notice.webp": [
      mark([1022, 52, 404, 82], [1042, 25], "Selecting SPS, Packeta or Slovenská pošta creates an archived closure schedule. Open it from this link or later from the menu.", "Výber SPS, Packety alebo Slovenskej pošty vytvorí archivovaný plán uzávierky. Otvoríte ho týmto odkazom alebo neskôr z menu."),
      mark([758, 52, 146, 36], [895, 133], "The Closure Schedules counter on the method now shows the new schedule.", "Počítadlo Closure Schedules na metóde teraz ukazuje nový plán."),
      mark([878, 622, 40, 26], [973, 635], "The selected carrier is stored on the delivery method.", "Vybraný dopravca je uložený na dopravnej metóde."),
    ],
    "38-sms-prompt.webp": [
      mark([320, 554, 108, 41], [402, 647], "Odoo asks once whether to text customers when a delivery is validated. Disable SMS (or Confirm) and the validation continues.", "Odoo sa raz opýta, či posielať zákazníkom SMS pri validácii dodávky. Zvoľte Disable SMS (alebo Confirm) a validácia pokračuje."),
    ],
    "39-two-boxes.webp": [
      mark([780, 473, 63, 29], [725, 488], "Details → Destination Package assigns the packed quantity to a box.", "Details → Destination Package priradí zabalené množstvo do škatule."),
      mark([361, 464, 217, 92], [627, 536], "Each outer box is a destination package. Neoship gets one parcel per outermost package.", "Každá vonkajšia škatuľa je cieľový balík (Destination Package). Neoship dostane jeden kus za každý vonkajší balík."),
      mark([612, 50, 112, 41], [590, 124], "Packages lists the boxes of this transfer; after sending, each box shows its Neoship tracking.", "Packages zobrazí škatule tohto dodacieho listu; po odoslaní má každá svoje sledovacie číslo Neoship."),
    ],
    "40-split-boxes.webp": [
      mark([243, 443, 954, 46], [1252, 466], "Line 1: 8 bags in Krabica 1/2.", "Riadok 1: 8 balíčkov v Krabica 1/2."),
      mark([243, 481, 954, 46], [1234, 524], "Add a line: the remaining 7 bags in Krabica 2/2. Each Packeta box must weigh at most 15 kg.", "Add a line: zvyšných 7 balíčkov v Krabica 2/2. Každý balík Packety môže mať najviac 15 kg."),
      mark([242, 689, 60, 41], [332, 763], "Save, then Validate the same delivery again.", "Uložte a znova validujte ten istý dodací list."),
    ],
    "41-package-tracking.webp": [
      mark([308, 470, 283, 46], [500, 568], "Each Packeta box is its own shipment with its own tracking number.", "Každá škatuľa pre Packetu je samostatná zásielka s vlastným sledovacím číslom."),
      mark([583, 470, 273, 46], [885, 532], "The second box gets the reference with suffix -2.", "Druhá škatuľa dostane referenciu s príponou -2."),
      mark([1138, 470, 233, 46], [1403, 532], "Tracking updates the status of every box; the transfer shows the combined status.", "Sledovanie aktualizuje stav každej škatule; dodací list ukazuje súhrnný stav."),
    ],
    "42-pickup-then-courier.webp": [
      mark([153, 292, 103, 24], [311, 304], "This backorder continues BA/OUT/00019, which the customer picked up in person.", "Tento nedodaný zvyšok pokračuje po BA/OUT/00019, ktorý si zákazníčka vyzdvihla osobne."),
      mark([184, 466, 72, 24], [311, 478], "The rest goes by courier: Kuriér SPS.", "Zvyšok ide kuriérom: Kuriér SPS."),
      mark([352, 709, 110, 46], [502, 771], "The courier collects only these 2 bags: 69.80 €. The shipping line counted towards the first delivery, the pickup.", "Kuriér vyberie iba tieto 2 balíčky: 69,80 €. Riadok dopravy sa započítal do prvej dodávky, teda osobného odberu."),
    ],
    "43-kit-components.webp": [
      mark([13, 464, 266, 134], [146, 653], "The kit is delivered as its components: coffee and mug, 2 of each for 2 sets.", "Sada sa dodáva ako jej komponenty: káva a hrnček, pre 2 sady po 2 kusy."),
      mark([673, 527, 110, 71], [756, 650], "Only 1 mug is ready, so this delivery contains 1 complete set and 1 extra coffee.", "Pripravený je iba 1 hrnček, takže táto dodávka obsahuje 1 celú sadu a 1 kávu navyše."),
    ],
    "44-kit-cod.webp": [
      mark([659, 190, 110, 32], [714, 277], "BA/OUT/00020 collects 1 complete set and the shipping: 22.90 € + 3.90 € = 26.80 €.", "BA/OUT/00020 vyberie 1 celú sadu a dopravu: 22,90 € + 3,90 € = 26,80 €."),
      mark([659, 150, 110, 32], [604, 166], "The backorder completes the second set and collects the rest: 22.90 €. The extra coffee from the first delivery is paid with this set.", "Nedodaný zvyšok dokončí druhú sadu a vyberie zvyšok: 22,90 €. Káva navyše z prvej dodávky sa zaplatí s touto sadou."),
    ],
    "45-discount-order.webp": [
      mark([13, 492, 958, 50], [1026, 517], "A fixed discount of 20 € added with the Discount button is a service line, like the shipping.", "Pevná zľava 20 € pridaná tlačidlom Discount je riadok služby, rovnako ako doprava."),
      mark([687, 636, 201, 75], [943, 674], "Order total: 3 × 12.90 € + 3.90 € − 20.00 € = 22.60 €.", "Suma objednávky: 3 × 12,90 € + 3,90 € − 20,00 € = 22,60 €."),
    ],
    "46-discount-cod.webp": [
      mark([661, 190, 110, 32], [606, 206], "The first delivery would be 12.90 € + 3.90 € − 20.00 € = −3.20 €, so it goes without cash on delivery.", "Prvá dodávka by vyšla 12,90 € + 3,90 € − 20,00 € = −3,20 €, preto odíde bez dobierky."),
      mark([661, 150, 110, 32], [621, 130], "The next delivery deducts the 3.20 €: 25.80 € − 3.20 € = 22.60 €, exactly the order total.", "Ďalšia dodávka odpočíta 3,20 €: 25,80 € − 3,20 € = 22,60 €, presne suma objednávky."),
    ],
    "47-new-order.webp": [
      mark([107, 222, 137, 94], [299, 269], "Select the customer.", "Vyberte zákazníka."),
      mark([47, 520, 97, 24], [185, 566], "Add a product adds an order line.", "Add a product pridá riadok objednávky."),
      mark([13, 427, 892, 89], [960, 472], "Stocked products with their quantities.", "Skladové produkty s množstvami."),
    ],
    "48-order-tag.webp": [
      mark([135, 349, 108, 47], [298, 372], "Open Other Info.", "Otvorte Ďalšie informácie (Other Info)."),
      mark([176, 656, 93, 29], [324, 670], "The payment tag Dobierka matches the cash on delivery rule.", "Platobný štítok Dobierka spĺňa pravidlo dobierky."),
    ],
    "49-order-confirm.webp": [
      mark([13, 511, 892, 50], [960, 536], "The shipping line has the fixed price of the method.", "Riadok dopravy má pevnú cenu metódy."),
      mark([687, 655, 201, 75], [943, 692], "For a COD order, the courier collects this total including shipping and VAT.", "Pri dobierke kuriér vyberie túto celkovú sumu vrátane dopravy a DPH."),
      mark([127, 109, 82, 41], [236, 183], "Confirm turns the quotation into a sales order and creates the delivery.", "Potvrdiť (Confirm) zmení ponuku na predajnú objednávku a vytvorí dodací list."),
    ],
    "25-protocol-history.webp": [
      mark([766, 150, 65, 27], [800, 260], "Each closure adds a row: Closed, Nothing to Close or Failed.", "Každá uzávierka pridá riadok: Closed, Nothing to Close alebo Failed."),
      mark([997, 152, 236, 24], [1125, 260], "Download the protocol PDF returned by the carrier.", "Stiahnite PDF protokol, ktorý vrátil dopravca."),
    ],
  };

  const slovak = document.documentElement.lang === "sk";
  const text = slovak ? {
    hide: "Skryť značky na obrázkoch",
    show: "Zobraziť značky na obrázkoch",
  } : {
    hide: "Hide screenshot guides",
    show: "Show screenshot guides",
  };
  const svgNS = "http://www.w3.org/2000/svg";
  const svgElement = (tag, attributes) => {
    const element = document.createElementNS(svgNS, tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
    return element;
  };

  for (const button of document.querySelectorAll("main .shot")) {
    const image = button.querySelector("img");
    const notes = guides[image.getAttribute("src").split("/").at(-1)];
    if (!notes) continue;
    const width = Number(image.getAttribute("width"));
    const height = Number(image.getAttribute("height"));
    const stage = document.createElement("span");
    stage.className = "screenshot-stage";
    button.append(stage);
    stage.append(image);
    const svg = svgElement("svg", { class: "guide-overlay", viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true", focusable: "false" });
    stage.append(svg);
    notes.forEach(({ box, pin }, index) => {
      const [x, y, w, h] = box;
      const [px, py] = pin;
      // Aim at the nearest edge, not over the field's text or checkbox.
      const tx = Math.max(x, Math.min(px, x + w));
      const ty = Math.max(y, Math.min(py, y + h));
      const angle = Math.atan2(ty - py, tx - px);
      const head = 14;
      const wing = 7;
      const hx = tx - head * Math.cos(angle);
      const hy = ty - head * Math.sin(angle);
      svg.append(svgElement("rect", { x, y, width: w, height: h, rx: 5, class: "guide-box-halo" }));
      svg.append(svgElement("rect", { x, y, width: w, height: h, rx: 5, class: "guide-box" }));
      const line = { x1: px, y1: py, x2: hx, y2: hy };
      svg.append(svgElement("line", { ...line, class: "guide-arrow-halo" }));
      svg.append(svgElement("line", { ...line, class: "guide-arrow" }));
      svg.append(svgElement("polygon", {
        points: `${tx},${ty} ${hx + wing * Math.sin(angle)},${hy - wing * Math.cos(angle)} ${hx - wing * Math.sin(angle)},${hy + wing * Math.cos(angle)}`,
        class: "guide-arrow-head",
      }));
      const marker = document.createElement("span");
      marker.className = "guide-marker";
      marker.setAttribute("aria-hidden", "true");
      marker.style.left = `${px / width * 100}%`;
      marker.style.top = `${py / height * 100}%`;
      marker.textContent = String.fromCharCode(97 + index);
      stage.append(marker);
    });
  }

  for (const toggle of document.querySelectorAll("[data-guides-toggle]")) {
    toggle.hidden = false;
    toggle.textContent = text.hide;
    toggle.setAttribute("aria-pressed", "true");
    toggle.addEventListener("click", () => {
      const hidden = document.body.classList.toggle("guides-hidden");
      toggle.textContent = hidden ? text.show : text.hide;
      toggle.setAttribute("aria-pressed", String(!hidden));
    });
  }
})();
