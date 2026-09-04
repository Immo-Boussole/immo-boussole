#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.csv_service import fix_mojibake, decode_csv_bytes

def test_fix_mojibake_strings():
    assert fix_mojibake('Contrat de sÃ©curitÃ©') == 'Contrat de sécurité'
    assert fix_mojibake('Salle Ã  manger') == 'Salle à manger'
    assert fix_mojibake('RÃ©frigÃ©rateur amÃ©ricain') == 'Réfrigérateur américain'
    assert fix_mojibake('Ã nÃ©gocier') == 'À négocier'
    assert fix_mojibake('Toile grise, mÃ¢t') == 'Toile grise, mât'
    assert fix_mojibake('Salon séjour propre') == 'Salon séjour propre'

def test_decode_csv_bytes_encodings():
    original_csv = 'id;type;piece;titre;statut_negociation\n1;objet;Salle à manger;Table en chêne;À négocier\n'
    b_utf8 = original_csv.encode('utf-8')
    assert 'Salle à manger' in decode_csv_bytes(b_utf8)
    b_utf8_bom = b'\xef\xbb\xbf' + original_csv.encode('utf-8')
    assert 'Salle à manger' in decode_csv_bytes(b_utf8_bom)
    b_cp1252 = original_csv.encode('cp1252')
    assert 'Salle à manger' in decode_csv_bytes(b_cp1252)
    b_latin1 = original_csv.encode('latin-1')
    assert 'Salle à manger' in decode_csv_bytes(b_latin1)

    corrupted_str = 'id;type;piece;titre;statut_negociation\n1;objet;Salle Ã  manger;Table en chÃªne;Ã nÃ©gocier\n'
    b_corrupted = corrupted_str.encode('utf-8')
    decoded = decode_csv_bytes(b_corrupted)
    assert 'Salle à manger' in decoded
    assert 'Table en chêne' in decoded
    assert 'À négocier' in decoded

if __name__ == '__main__':
    test_fix_mojibake_strings()
    test_decode_csv_bytes_encodings()
    print('ALL ENCODING TESTS PASSED!')
