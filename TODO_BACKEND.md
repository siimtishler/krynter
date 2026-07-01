# Backend TODO

1. Let users choose POI `alamgrupp` filters and per-group item counts.
So create a new button "Seadista" that opens a menu box in the centre where I can set all the POI settings.
This means I can chose how many museums, bus stops etc they want to see from a single group.
The groups will still remain to be Haridus ja lapsed, Igapäevateenused to Transport, but the user can choose what and how many alamgrupp POIs they want to see. The default is already in constants.py as `POI_CATEGORIES`. You can use the same structure for this. So frontend can send a new POI_CATEGORIES.
The POI settings should be saved into a poi-settings.json file in the backend.
2. Send noise areas to the frontend. Already created endpoints for this in map.js and api.py
Make it possible to display the noise area with a similar button like the detail plans, but this wont be debug attribute. The noise area on the map will have the same colors as the noise-meter. The noise data itself is in 5dB steps from 45-70
3. Additionally download the JN100<name>.pdf this is the detail plan image/figure and save it to the same place where the SK is saved. I already made a starting change in pdfs.py.
Instead of Laadi PDF, create Laadi seletuskiri and Laadi detailplaneering buttons on the frontend that request these files from the backend. Upon pressing it downloads it. 
4. Move the AI loader down 1 step so its below the analyze, and download file buttons, but it should span from left to right so make it bigger


Second iteration:
Instead of getting to edit everything (names, labels, queryable groups (grupp, alamgrupp, etc)) I only want to be able to actully edit the number of POIs. This means the poi setting query fields and labels are set in stone. E.g under Sport ja liikumine there are 3 subgroups:
Sport, Terviserada and Supluskoht now only thing I can change there is the number, from 0-5. 
There will only exist 2 buttons there Save and Reset, reset puts back the default intial state, but pressing save is still required. Also add the same colored orbs to the menu also like poi-swatch.
Also when I try to enter numbers outside of 0-5 range it gives an english language popup. Make a custom styled popup in estonian instead please.

Make the poi-settings-categories foldable/collapsable and reopenable, because this menu is quite large. Also I think when we have enough room we can have 2 poi-settings-categories next to each other now, as we are removing the query-field, query-label and the secondary buttons "Eemalda" and "Lisa" secondary buttons there

The download should download the Seletuskiri and detailplaneering with proper names. If its seletuskiri, then download it with a correct name also, the name should be the address selected + type of file (detail_planeering or seletuskiri) E.g J. Poska tn 35 is selected I will get j_poska_tn_35_seletuskiri.pdf or smth like that.

3rd iteration:
The state of poi-settings.json atm should also be the DEFAULT state of the settings. Go back to this state when Lähtesta is pressed.

When I open or close a poi-settings category it also makes the poi-settings category next to it also get bigger or smaller. But it shouldnt affect the other column poi category next to it. E.g Haridus ja Lapsed is in state open but next to it Tervis is not but its the same height as Haridus ja lapsed. 

The input query-limit buttons should also only support the range of 0-5
Query-limit with 0 values should have slightly greyed out background.
I should be able to completely disable some category. E.g I can press on the poi-swatch next to the span and it just greys out everything in that category, as if they were 0's, but it doesnt actually remove the values entered into the the query limit, it can just send an additional boolean field like "user-disabled" to the backend. If something is user-disabled the span in the poi-settings-category-header should also get color grey for example. Or some other way of indicating its disabled. A poi-settings-category gets "user-disabled" if either all values in it are 0 or the swatch was clicked. This should also be saved to the poi-settings.json

The lähtesta and Salvesta buttons should be sticky, so that they are always clickable and I dont have to scroll to the bottom.

Also add back a sticky Sulge button for the menu to the top right, only way to close it atm is to either press Salvesta or somewhere outside of the menu.

The Näita kaardil and Seadista buttons are right next to eachother, add some margin between them

Also make a button for poi-groups to open or close all and also option to open or close each individually

Whenever I download a PDF it still gives it the name download (<num>).pdf. 
Can this even be changed?

# TODO Regex:
- Prefer `Aadress.pindala` when `Krundi pind/suurus` from the PDF differs significantly from cadastre area.
- Remove `omandivorm`, `kasutusotstarve/sihtotstarve`, and allowed building count from building-right analysis output. Also dont pass these to the LLM anymore
