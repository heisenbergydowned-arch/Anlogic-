cd [file dirname [info script]]
import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db build_008/alarm_only.pr.db
bitgen -bit regenerated_cooling_link.bit
