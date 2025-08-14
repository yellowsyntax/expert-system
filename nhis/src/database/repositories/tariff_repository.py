from typing import List, Optional, Dict, Any, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
from datetime import datetime, timedelta
import uuid

from .base_repository import BaseRepository

class TariffRepository(BaseRepository):
    def __init__(self, db_session: Session):
        super().__init__(db_session, None)
        self.db_session = db_session
    
    def get_gdrg_tariff(self, gdrg_code: str, facility_level: str, age_suffix: str = 'A') -> Optional[float]:
        from ..models.icd10_code import ICD10Code
        
        full_gdrg_code = f"{gdrg_code}{age_suffix}"
        
        tariff_record = self.db_session.query(ICD10Code).filter(
            and_(
                ICD10Code.gdrg_code == full_gdrg_code,
                ICD10Code.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(tariff_record.tariff) if tariff_record and tariff_record.tariff else None
    
    def get_investigation_tariff(self, investigation_code: str) -> Optional[float]:
        from ..models.investigation import Investigation
        
        investigation = self.db_session.query(Investigation).filter(
            Investigation.inv_code == investigation_code
        ).first()
        
        return float(investigation.tariff) if investigation and investigation.tariff else None
    
    def get_zoom_procedure_tariff(self, zoom_code: str, facility_level: str) -> Optional[float]:
        from ..models.zoom_code import ZoomCode
        
        zoom_procedure = self.db_session.query(ZoomCode).filter(
            and_(
                ZoomCode.zoom_code == zoom_code,
                ZoomCode.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(zoom_procedure.tariff) if zoom_procedure and zoom_procedure.tariff else None
    
    def get_opd_procedure_tariff(self, opd_code: str, facility_level: str) -> Optional[float]:
        from ..models.opd_procedure import OPDProcedure
        
        opd_procedure = self.db_session.query(OPDProcedure).filter(
            and_(
                OPDProcedure.opd_code == opd_code,
                OPDProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(opd_procedure.tariff) if opd_procedure and opd_procedure.tariff else None
    
    def get_dental_procedure_tariff(self, dent_code: str, facility_level: str) -> Optional[float]:
        from ..models.dent_procedure import DentProcedure
        
        dental_procedure = self.db_session.query(DentProcedure).filter(
            and_(
                DentProcedure.dent_code == dent_code,
                DentProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(dental_procedure.tariff) if dental_procedure and dental_procedure.tariff else None
    
    def get_ent_procedure_tariff(self, ent_code: str, facility_level: str) -> Optional[float]:
        from ..models.ent_procedure import ENTProcedure
        
        ent_procedure = self.db_session.query(ENTProcedure).filter(
            and_(
                ENTProcedure.ent_code == ent_code,
                ENTProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(ent_procedure.tariff) if ent_procedure and ent_procedure.tariff else None
    
    def get_medicine_procedure_tariff(self, medi_code: str, facility_level: str) -> Optional[float]:
        from ..models.medicine_procedure import MedicineProcedure
        
        medicine_procedure = self.db_session.query(MedicineProcedure).filter(
            and_(
                MedicineProcedure.medi_code == medi_code,
                MedicineProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(medicine_procedure.tariff) if medicine_procedure and medicine_procedure.tariff else None
    
    def get_paediatric_procedure_tariff(self, paed_code: str, facility_level: str) -> Optional[float]:
        from ..models.paediatric_procedure import PaediatricProcedure
        
        paed_procedure = self.db_session.query(PaediatricProcedure).filter(
            and_(
                PaediatricProcedure.paed_code == paed_code,
                PaediatricProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(paed_procedure.tariff) if paed_procedure and paed_procedure.tariff else None
    
    def get_surgery_procedure_tariff(self, surg_code: str, facility_level: str) -> Optional[float]:
        from ..models.surgery_procedure import SurgeryProcedure
        
        surgery_procedure = self.db_session.query(SurgeryProcedure).filter(
            and_(
                SurgeryProcedure.surg_code == surg_code,
                SurgeryProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).first()
        
        return float(surgery_procedure.tariff) if surgery_procedure and surgery_procedure.tariff else None
    
    def get_medicine_price(self, medicine_code: str) -> Optional[Dict[str, Any]]:
        from ..models.medicines import Medicines
        
        medicine = self.db_session.query(Medicines).filter(
            Medicines.code == medicine_code
        ).first()
        
        if medicine:
            return {
                'code': medicine.code,
                'generic_name': medicine.generic_name,
                'unit_of_pricing': medicine.unit_of_pricing,
                'price': float(medicine.price) if medicine.price else None,
                'level_of_prescribing': medicine.level_of_prescribing
            }
        
        return None
    
    def get_comprehensive_tariff(self, service_code: str, service_type: str, facility_level: str, age_suffix: str = 'A') -> Dict[str, Any]:
        result = {
            'service_code': service_code,
            'service_type': service_type,
            'facility_level': facility_level,
            'tariff_amount': None,
            'found': False,
            'source_table': None
        }
        
        tariff_methods = {
            'GDRG': lambda: self.get_gdrg_tariff(service_code, facility_level, age_suffix),
            'INVESTIGATION': lambda: self.get_investigation_tariff(service_code),
            'ZOOM': lambda: self.get_zoom_procedure_tariff(service_code, facility_level),
            'OPD': lambda: self.get_opd_procedure_tariff(service_code, facility_level),
            'DENTAL': lambda: self.get_dental_procedure_tariff(service_code, facility_level),
            'ENT': lambda: self.get_ent_procedure_tariff(service_code, facility_level),
            'MEDICINE_PROC': lambda: self.get_medicine_procedure_tariff(service_code, facility_level),
            'PAEDIATRIC': lambda: self.get_paediatric_procedure_tariff(service_code, facility_level),
            'SURGERY': lambda: self.get_surgery_procedure_tariff(service_code, facility_level),
            'MEDICINE': lambda: self.get_medicine_price(service_code)
        }
        
        if service_type in tariff_methods:
            tariff_data = tariff_methods[service_type]()
            
            if tariff_data:
                if service_type == 'MEDICINE':
                    result['tariff_amount'] = tariff_data.get('price')
                    result['medicine_details'] = tariff_data
                else:
                    result['tariff_amount'] = tariff_data
                
                result['found'] = True
                result['source_table'] = service_type
        
        return result
    
    def get_facility_authorized_gdrgs(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.icd10_code import ICD10Code
        
        gdrg_records = self.db_session.query(ICD10Code).filter(
            and_(
                ICD10Code.gdrg_code.isnot(None),
                ICD10Code.level_of_care.contains({facility_level: True}) if facility_level else True
            )
        ).all()
        
        authorized_gdrgs = []
        for record in gdrg_records:
            authorized_gdrgs.append({
                'icd_code': record.icd_code,
                'diagnosis_description': record.diagnosis_description,
                'gdrg_code': record.gdrg_code,
                'gdrg_name': record.gdrg_name,
                'tariff': float(record.tariff) if record.tariff else None,
                'level_of_care': record.level_of_care
            })
        
        return authorized_gdrgs
    
    def get_facility_authorized_procedures(self, facility_level: str, procedure_type: str = 'ALL') -> List[Dict[str, Any]]:
        authorized_procedures = []
        
        if procedure_type in ['ALL', 'ZOOM']:
            zoom_procedures = self._get_zoom_procedures_for_level(facility_level)
            authorized_procedures.extend(zoom_procedures)
        
        if procedure_type in ['ALL', 'OPD']:
            opd_procedures = self._get_opd_procedures_for_level(facility_level)
            authorized_procedures.extend(opd_procedures)
        
        if procedure_type in ['ALL', 'DENTAL']:
            dental_procedures = self._get_dental_procedures_for_level(facility_level)
            authorized_procedures.extend(dental_procedures)
        
        if procedure_type in ['ALL', 'ENT']:
            ent_procedures = self._get_ent_procedures_for_level(facility_level)
            authorized_procedures.extend(ent_procedures)
        
        if procedure_type in ['ALL', 'SURGERY']:
            surgery_procedures = self._get_surgery_procedures_for_level(facility_level)
            authorized_procedures.extend(surgery_procedures)
        
        if procedure_type in ['ALL', 'PAEDIATRIC']:
            paed_procedures = self._get_paediatric_procedures_for_level(facility_level)
            authorized_procedures.extend(paed_procedures)
        
        return authorized_procedures
    
    def _get_zoom_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.zoom_code import ZoomCode
        
        procedures = self.db_session.query(ZoomCode).filter(
            ZoomCode.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.zoom_code,
                'description': p.description,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'ZOOM',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def _get_opd_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.opd_procedure import OPDProcedure
        
        procedures = self.db_session.query(OPDProcedure).filter(
            OPDProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.opd_code,
                'description': p.name,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'OPD',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def _get_dental_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.dent_procedure import DentProcedure
        
        procedures = self.db_session.query(DentProcedure).filter(
            DentProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.dent_code,
                'description': p.description,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'DENTAL',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def _get_ent_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.ent_procedure import ENTProcedure
        
        procedures = self.db_session.query(ENTProcedure).filter(
            ENTProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.ent_code,
                'description': p.description,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'ENT',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def _get_surgery_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.surgery_procedure import SurgeryProcedure
        
        procedures = self.db_session.query(SurgeryProcedure).filter(
            SurgeryProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.surg_code,
                'description': p.description,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'SURGERY',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def _get_paediatric_procedures_for_level(self, facility_level: str) -> List[Dict[str, Any]]:
        from ..models.paediatric_procedure import PaediatricProcedure
        
        procedures = self.db_session.query(PaediatricProcedure).filter(
            PaediatricProcedure.level_of_care.contains({facility_level: True}) if facility_level else True
        ).all()
        
        return [
            {
                'code': p.paed_code,
                'description': p.description,
                'tariff': float(p.tariff) if p.tariff else None,
                'type': 'PAEDIATRIC',
                'level_of_care': p.level_of_care
            } for p in procedures
        ]
    
    def calculate_gdrg_amount_with_modifiers(self, gdrg_code: str, facility_level: str, age_suffix: str,
                                           modifiers: List[Dict[str, Any]]) -> Dict[str, Any]:
        base_tariff = self.get_gdrg_tariff(gdrg_code, facility_level, age_suffix)
        
        if not base_tariff:
            return {
                'error': f'No tariff found for G-DRG {gdrg_code}{age_suffix} at level {facility_level}',
                'base_tariff': None,
                'final_amount': None
            }
        
        calculation_breakdown = {
            'base_gdrg_code': f"{gdrg_code}{age_suffix}",
            'facility_level': facility_level,
            'base_tariff': base_tariff,
            'modifiers_applied': [],
            'total_modifier_percentage': 0,
            'modifier_amount': 0,
            'final_amount': base_tariff
        }
        
        current_amount = base_tariff
        total_modifier_percentage = 0
        
        for modifier in modifiers:
            modifier_type = modifier.get('type')
            modifier_percentage = modifier.get('percentage', 0)
            modifier_fixed_amount = modifier.get('fixed_amount', 0)
            
            if modifier_percentage > 0:
                modifier_amount = current_amount * (modifier_percentage / 100)
                current_amount += modifier_amount
                total_modifier_percentage += modifier_percentage
                
                calculation_breakdown['modifiers_applied'].append({
                    'type': modifier_type,
                    'percentage': modifier_percentage,
                    'amount_added': modifier_amount
                })
            
            if modifier_fixed_amount > 0:
                current_amount += modifier_fixed_amount
                
                calculation_breakdown['modifiers_applied'].append({
                    'type': modifier_type,
                    'fixed_amount': modifier_fixed_amount,
                    'amount_added': modifier_fixed_amount
                })
        
        calculation_breakdown['total_modifier_percentage'] = total_modifier_percentage
        calculation_breakdown['modifier_amount'] = current_amount - base_tariff
        calculation_breakdown['final_amount'] = current_amount
        
        return calculation_breakdown
    
    def get_tariff_statistics(self, facility_level: Optional[str] = None) -> Dict[str, Any]:
        from ..models.icd10_code import ICD10Code
        from ..models.investigation import Investigation
        from ..models.zoom_code import ZoomCode
        from ..models.medicines import Medicines
        
        stats = {}
        
        gdrg_query = self.db_session.query(ICD10Code).filter(ICD10Code.tariff.isnot(None))
        if facility_level:
            gdrg_query = gdrg_query.filter(ICD10Code.level_of_care.contains({facility_level: True}))
        
        gdrg_tariffs = [float(record.tariff) for record in gdrg_query.all() if record.tariff]
        
        if gdrg_tariffs:
            stats['gdrg_tariffs'] = {
                'count': len(gdrg_tariffs),
                'min': min(gdrg_tariffs),
                'max': max(gdrg_tariffs),
                'average': sum(gdrg_tariffs) / len(gdrg_tariffs),
                'total_value': sum(gdrg_tariffs)
            }
        
        investigation_tariffs = [float(inv.tariff) for inv in self.db_session.query(Investigation).all() if inv.tariff]
        if investigation_tariffs:
            stats['investigation_tariffs'] = {
                'count': len(investigation_tariffs),
                'min': min(investigation_tariffs),
                'max': max(investigation_tariffs),
                'average': sum(investigation_tariffs) / len(investigation_tariffs)
            }
        
        zoom_query = self.db_session.query(ZoomCode).filter(ZoomCode.tariff.isnot(None))
        if facility_level:
            zoom_query = zoom_query.filter(ZoomCode.level_of_care.contains({facility_level: True}))
        
        zoom_tariffs = [float(zoom.tariff) for zoom in zoom_query.all() if zoom.tariff]
        if zoom_tariffs:
            stats['zoom_procedure_tariffs'] = {
                'count': len(zoom_tariffs),
                'min': min(zoom_tariffs),
                'max': max(zoom_tariffs),
                'average': sum(zoom_tariffs) / len(zoom_tariffs)
            }
        
        medicine_prices = [float(med.price) for med in self.db_session.query(Medicines).all() if med.price]
        if medicine_prices:
            stats['medicine_prices'] = {
                'count': len(medicine_prices),
                'min': min(medicine_prices),
                'max': max(medicine_prices),
                'average': sum(medicine_prices) / len(medicine_prices)
            }
        
        return stats