# coding=utf-8
from __future__ import unicode_literals
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.encoding import python_2_unicode_compatible, smart_text
from django.db import models
from django_apogee.models import Pays, InsAdmEtp, Etape
from yaml.parser import ParserError

from duck_examen.managers import ExamenCenterManager
import re
import yaml
from duck_utils.models import Salle


class EtapeExamen(InsAdmEtp):
    class Meta:
        proxy = True
        verbose_name = 'Etape examen'


@python_2_unicode_compatible
class ExamCenter(models.Model):
    u"""
    Centre de gestion : Présentiel, etranger et dom-tom
    is_open : ouvre à l'application
    has_demande_ratachement : pour les examens à l'etranger true
    is_centre_principal : indique les centres métropolitains
    """
    label = models.CharField("center name", max_length=200, null=True)
    mailling_address = models.TextField("Adresse du centre")
    sending_address = models.TextField(u"Adresse de l'envoi du matériel", blank=True, null=True)
    last_name_manager = models.CharField(max_length=30, null=True, blank=True)
    first_name = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    email_bis = models.EmailField(null=True, blank=True, verbose_name="second email")
    phone = models.CharField(max_length=30, blank=True, null=True)
    fax = models.CharField(max_length=30, null=True, blank=True)
    country = models.ForeignKey(Pays, verbose_name="pays", null=True)

    is_open = models.BooleanField(default=True, verbose_name='Ouvert')
    has_incorporation = models.BooleanField(default=True, verbose_name="Demande rattachement",
                                            help_text=u"l'étudiant doit faire une demande de rattachement")
    is_main_center = models.BooleanField(default=False)
    objects = ExamenCenterManager()

    class Meta:
        verbose_name = "Centre examen"
        verbose_name_plural = "Centres examens"

    def __str__(self):
        return u"{} {}".format(smart_text(self.label), self.country)

    def name_by_pays(self):
        return u"{} {}".format(self.country, smart_text(self.label))

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if not self.sending_address:
            self.sending_address = self.mailling_address
        super(ExamCenter, self).save(force_insert, force_update, using, update_fields)

    def etudiant_by_step_session(self, cod_etp, session, amenagement_examen=None, parcours=-1):
        # type (int, int, AmenagementExamenModel,Parcours) -> django.db.models.query.QuerySet
        filters = {
            'inscription__cod_etp': cod_etp,
            'inscription__cod_anu': 2015,
            'session': session,
        }
        if amenagement_examen:
            filters['type_amenagement'] = amenagement_examen
        if parcours != -1:
            filters['parcours'] = parcours

        query = self.rattachementcentreexamen_set.filter(** filters)
        return query.order_by('inscription__cod_ind__lib_nom_pat_ind').distinct()

    def nb_etudiant(self, cod_etp, session, amenagement_examen=None, parcours=-1):
        # type (int, int, AmenagementExamenModel,Parcours) -> django.db.models.query.QuerySet
        return self.etudiant_by_step_session(cod_etp, session, amenagement_examen=amenagement_examen, parcours=parcours).count()

@python_2_unicode_compatible
class AmenagementExamenModel(models.Model):
    TYPE_AMENAGEMENT = (
        ('N', 'Normal'),
        ('T', 'Tiers-temps')
    )
    type_amenagement = models.CharField(max_length=2,
                                        choices=TYPE_AMENAGEMENT, default='N',
                                        primary_key=True)

    def __str__(self):
        return "{}".format(self.get_type_amenagement_display())

@python_2_unicode_compatible
class Parcours(models.Model):
    etape = models.ForeignKey(Etape)
    label = models.CharField(max_length=256, default="NO NAME")

    def __str__(self):
        return "{} {} ".format(self.etape, self.label)

@python_2_unicode_compatible
class RattachementCentreExamen(models.Model):
    inscription = models.ForeignKey(InsAdmEtp)
    # cle composite insadmetp
    # cod_anu = models.CharField(max_length=4, db_column="COD_ANU")
    # cod_ind = models.CharField(max_length=8, db_column='COD_IND', primary_key=True)
    # cod_etp = models.CharField(u"(COPIED)(COPIED)Code Etape", max_length=6, null=True, db_column="COD_ETP")
    # cod_vrs_vet = models.CharField(u"(COPIED)Numero Version Etape", max_length=3, null=True, db_column="COD_VRS_VET")
    # num_occ_iae = models.CharField(u"", max_length=2, null=True, db_column="NUM_OCC_IAE")
    #/ cle composite
    session = models.CharField(max_length=2, choices=(('1', 'Première session'), ('2', 'Seconde session')))
    centre = models.ForeignKey(ExamCenter, null=True)
    ec_manquant = models.BooleanField(default=False, blank=True)
    type_examen = models.ForeignKey('TypeExamen', default='D')
    salle = models.ForeignKey(Salle, blank=True, null=True)
    handicap = models.BooleanField(default=False)
    type_amenagement = models.ForeignKey('AmenagementExamenModel', default='N')
    parcours = models.ForeignKey('Parcours', null=True, blank=True)

    def get_dates(self):
        d = DeroulementExamenModel.objects.get(etape__cod_etp=self.inscription.cod_etp, session=self.session).get_deroulement_parse(self.type_examen)
        return [date['date'] for date in d]

    def __str__(self):
        return u"{} session : {} ec manquant : {}".format(self.centre, self.session, "oui" if self.ec_manquant else 'non')

    def get_salle(self):
        if self.salle:
            return self.salle.label
        elif not self.centre.is_main_center:
            return self.centre.mailling_address
        else:
            return DeroulementExamenModel.objects.get(etape__cod_etp=self.inscription.cod_etp,
                                                      session=self.session).salle_examen
    def get_centre(self):
        return self.centre.mailling_address
            # recuperer le deroule et sa salle

    def get_etp_ant(self):
        code_etp_actuel = self.inscription.cod_etp
        if code_etp_actuel[0] == 'L' and code_etp_actuel != 'L3NEDU':
            if code_etp_actuel[1] in ['2', '3']:
                code_etp_anterieur = code_etp_actuel[0] + str(int(code_etp_actuel[1]) - 1) + code_etp_actuel[2:]
                cod_ind = self.inscription.cod_ind
                etp = InsAdmEtp.inscrits_condi.filter(cod_ind=cod_ind, cod_etp=code_etp_anterieur).first()
            if etp:
                return etp

        return None

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if not self.centre:
            self.centre = ExamCenter.objects.get(is_main_center=True)
        if self.ec_manquant:
            etp = self.get_etp_ant()
            if etp:
                r = RattachementCentreExamen.objects.get_or_create(inscription=etp, session=self.session)[0]
                r.centre = self.centre
                r.type_examen = self.type_examen
                r.save()

        RecapitulatifExamenModel.objects.get_or_create(session=self.session, centre=self.centre, etape_id=self.inscription.cod_etp)
        super(RattachementCentreExamen, self).save(force_insert, force_update, using, update_fields)


class EtapeExamenModel(Etape):
    """
    utiliser pour les examen
    """
    def get_etudiant_presentiel(self, session, amenagement_examen):
        qs = InsAdmEtp.inscrits_condi.filter(cod_etp=self.cod_etp,
                                             rattachementcentreexamen__centre__is_main_center=True,
                                             rattachementcentreexamen__session=session,
                                             rattachementcentreexamen__type_amenagement=amenagement_examen).order_by('cod_ind__lib_nom_pat_ind')
        return qs.distinct()

    class Meta:
        proxy = True
        ordering = ['cod_etp']


@python_2_unicode_compatible
class DeroulementExamenModel(models.Model):
    etape = models.ForeignKey(Etape)
    annee = models.CharField(max_length=4, default=2015, blank=True)
    session = models.CharField(max_length=2, choices=(('1', 'Première session'), ('2', 'Seconde session')))
    nb_salle = models.IntegerField('nombre de salle', null=True, blank=True)
    nb_table = models.IntegerField('nombre de table par salle', null=True, blank=True)
    deroulement = models.TextField('Le déroulement', help_text='chaque ec doit être séparé par un |', null=True,
                                   blank=True)
    date_examen = models.TextField('Date examen', null=True, blank=True)
    salle_examen = models.TextField('salles examens', null=True, blank=True)

    class Meta:
        verbose_name = "Deroulement"
        verbose_name_plural = "Deroulements"
        db_table = 'core_deroulementexemenmodel'  # faute ortho déjà mis en prod

    def derouler_par_parcours(self):
        result = {}
        if self.etape.parcours_set.count():
            for detail in self.detailderoulement_set.all():
                try:
                    result.setdefault(detail.parcours.label, []).append(detail)
                except AttributeError:
                    result.setdefault('Normal', []).append(detail)
        else:
            for detail in self.detailderoulement_set.all():
                result.setdefault('Normal', []).append(detail)
        return result


    def deroulement_etape_anterieur(self):
        code_etp_actuel = self.etape.cod_etp
        if code_etp_actuel[0] == 'L' and code_etp_actuel[1] in ['2', '3']:

            code_etp_anterieur = code_etp_actuel[0] + str(int(code_etp_actuel[1]) - 1) + code_etp_actuel[2:]
            return DeroulementExamenModel.objects.get(etape__cod_etp=code_etp_anterieur, session=self.session)
        else:
            return None

    def __str__(self):
        return '{} session {}'.format(self.etape, self.session)

    def get_deroulement_parse(self, amenagement_examen=AmenagementExamenModel.objects.get(type_amenagement='N'), parcours=None):
        return self.detailderoulement_set.get(amenagement_examen=amenagement_examen, parcours=parcours).deroulement_parse2()

    def get_deroulement_detail(self, amenagement_examen=AmenagementExamenModel.objects.get(type_amenagement='N'), parcours=None):
        return self.detailderoulement_set.get(amenagement_examen=amenagement_examen, parcours=parcours)


@python_2_unicode_compatible
class TypeExamen(models.Model):
    name = models.CharField(max_length=3, primary_key=True)
    label = models.CharField(max_length=30)

    def __str__(self):
        return self.label


@python_2_unicode_compatible
class DetailDeroulement(models.Model):
    deroulement = models.ForeignKey(DeroulementExamenModel, null=True, blank=True)
    amenagement_examen = models.ForeignKey(AmenagementExamenModel, default='N', blank=True)
    parcours = models.ForeignKey(Parcours, null=True, default=None, blank=True)
    # deroule = models.FileField(null=True, upload_to='deroule_examen', blank=True)
    deroulement_contenu = models.TextField('Le déroulement', help_text='chaque ec doit être séparé par un |', null=True,
                                   blank=True)

    def deroulement_parse2(self):
        """
        Ex: Liste de liste pour garder l'ordre des elements du fichier (le dico ne le permet pas)
- "JEUDI 03 SEPTEMBRE 2015":
    - "9h00 - 10h30":
        - AAAAAAAA|PSYCHO-SOCIO-PRAGMATIQUE DE LA COMMUNICATION|E. MARQUEZ
        - BBBBBBBB|INTERACTIONS SOCIALES|JL. TAVANI
    - "11h00 - 12h30":
        - CCCCCCCC|PSYCHOLOGIE DES ORGANISATIONS|B. VALLÉE
    - "14h00 - 15h30":
        - DDDDDDDD|PSYCHOLOGIE SOCIALE DE LA SANTÉ|L. DAGOT

- "VENDREDI 04 SEPTEMBRE 2015":
    - "7h00 - 8h30":
        - EEEEEEEE|ANGLAIS SPÉCIALISÉ|T. SAIAS

SORTIE:
[{'date': 'JEUDI 03 SEPTEMBRE 2015',
  'matieres': [{'ecs': [{'code_ec': 'AAAAAAAA',
                         'label': 'PSYCHO-SOCIO-PRAGMATIQUE DE LA COMMUNICATION',
                         'prof': 'E. MARQUEZ'},
                        {'code_ec': 'BBBBBBBB',
                         'label': 'INTERACTIONS SOCIALES',
                         'prof': 'JL. TAVANI'}],
                'heure_debut': '9h00',
                'heure_fin': '10h30'},
               {'ecs': [{'code_ec': u'CCCCCCCC',
                         'label': u'PSYCHOLOGIE DES ORGANISATIONS',
                         'prof': u'B. VALL\xc9E'}],
                'heure_debut': '11h00',
                'heure_fin': '12h30'},
               {'ecs': [{'code_ec': u'DDDDDDDD',
                         'label': u'PSYCHOLOGIE SOCIALE DE LA SANT\xc9',
                         'prof': u'L. DAGOT'}],
                'heure_debut': '14h00',
                'heure_fin': '15h30'}]},
 {'date': 'VENDREDI 04 SEPTEMBRE 2015',
  'matieres': [{'ecs': [{'code_ec': u'EEEEEEEE',
                         'label': u'ANGLAIS SP\xc9CIALIS\xc9',
                         'prof': u'T. SAIAS'}],
                'heure_debut': '7h00',
                'heure_fin': '8h30'}]}]

        """
        if not self.deroulement_contenu:
            return []
        text = self.deroulement_contenu.encode('utf-8')
        try:
            ylist = yaml.load(text.strip().rstrip())
        except ParserError:
            return []
        resultat = []
        for deroule_jour in ylist:
            jour = {'date': deroule_jour.keys()[0].strip().rstrip(), 'matieres': [], 'nb_ecs': 0}
            for j in deroule_jour[deroule_jour.keys()[0]]:
                heures = j.keys()[0].split('-')
                r = {
                    'heure_debut': heures[0].strip().rstrip(),
                    'heure_fin': heures[1].strip().rstrip(),
                    'ecs': []
                }
                for mat in j[j.keys()[0]]:
                    code_ec, label, prof = mat.split('|')
                    r['ecs'].append({'code_ec': code_ec, 'label': label, 'prof': prof})
                    jour['nb_ecs'] += 1
                jour['matieres'].append(r)
            resultat.append(jour)
        return resultat

    def get_jours(self):
        deroulement = self.deroulement_parse2()
        res = []
        for d in deroulement:
            res.append(d['date'])
        return res

    def __str__(self):
        return "{} {} {}".format(self.deroulement.etape, self.amenagement_examen , self.deroulement.session)


@python_2_unicode_compatible
class RecapitulatifExamenModel(models.Model):
    etape = models.ForeignKey(Etape)
    session = models.CharField(max_length=2, choices=(('1', 'Première session'), ('2', 'Seconde session')))
    centre = models.ForeignKey(ExamCenter)
    date_envoie = models.DateField("date envoie des envellopes", null=True, blank=True)
    date_reception = models.DateField("date réception des enveloppes", null=True, blank=True)
    anomalie = models.CharField('anomalie', max_length=200, null=True, blank=True)
    nb_enveloppe = models.IntegerField(null=True, blank=True)
    nb_colis = models.IntegerField(null=True, blank=True)

    class Meta:
        #app_label = 'core'
        verbose_name = 'Recap envoie'
        verbose_name_plural = 'Recaps envoie'
        # ordering = ['centre__country__lib_pay']

    def __str__(self):
        return '{} {} {}'.format(self.centre.name_by_pays(), self.etape_id, self.session)


class EtapeSettingsDerouleModel(models.Model):
    etape = models.ForeignKey(Etape)
    cod_anu = models.CharField(max_length=4, default='2015')

    date_envoi_convocation = models.DateField(null=True, blank=True) # for session 1
    envoi_convocation_processed = models.BooleanField(default=False) # If the command has been already executed or not
    session = models.CharField(max_length=2, choices=(('1', 'Première session'), ('2', 'Seconde session')))


    def get_deroulement(self):
        return self.etape.deroulementexamenmodel_set.get(session=self.session).get_deroulement_detail()

    def get_deroulement_parse(self):
        return self.etape.deroulementexamenmodel_set.get(session=self.session).get_deroulement_parse()

    def __str__(self):
        return "{} {} {}".format(self.etape, self.cod_anu, self.session)


@receiver(post_save, sender=InsAdmEtp)
def create_centre_rattachement_if_does_not_exist(sender, **kwargs):
    instance = kwargs.get('instance', None)
    if instance.tem_iae_prm == 'O':
        if not instance.rattachementcentreexamen_set.count():
            # il faut detecter s il y a des enfants
            code_etp_actuel = instance.cod_etp
            ec_manquant = False
            if code_etp_actuel[0] == 'L' and code_etp_actuel != 'L3NEDU':
                if code_etp_actuel[1] in ['2', '3']:
                    code_etp_anterieur = code_etp_actuel[0] + str(int(code_etp_actuel[1]) - 1) + code_etp_actuel[2:]
                    cod_ind = instance.cod_ind
                    etp = InsAdmEtp.inscrits_condi.filter(cod_ind=cod_ind, cod_etp=code_etp_anterieur).first()
                    ec_manquant = bool(etp)

            default_exam_center = ExamCenter.objects.get(is_main_center=True)
            for i in [1, 2]:
                try:
                    r = RattachementCentreExamen.objects.get(inscription=instance,
                                                                        session=i,
                                                                        ec_manquant=ec_manquant)
                    r.centre = default_exam_center
                    r.save()
                except RattachementCentreExamen.DoesNotExist:
                    r = RattachementCentreExamen(inscription=instance,
                                                session=i,
                                                ec_manquant=ec_manquant)
                    r.centre = default_exam_center
                    r.save()
