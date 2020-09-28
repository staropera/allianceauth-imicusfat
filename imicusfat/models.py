# -*- coding: utf-8 -*-

"""
the models
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models.query import QuerySet
from django.utils import timezone

from allianceauth.eveonline.models import EveCharacter
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


# Create your models here.
def get_sentinel_user():
    """
    get user or create one
    :return:
    """

    return User.objects.get_or_create(username="deleted")[0]


# Abstract model to allow for soft deletion
class SoftDeletionManager(models.Manager):
    """
    SoftDeletionManager
    """

    def __init__(self, *args, **kwargs):
        self.alive_only = kwargs.pop("alive_only", True)
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        """
        get_queryset
        :return:
        """

        if self.alive_only:
            return SoftDeletionQuerySet(self.model).filter(deleted_at=None)

        return SoftDeletionQuerySet(self.model)

    def hard_delete(self):
        """
        hard_delete
        :return:
        """

        return self.get_queryset().hard_delete()


class SoftDeletionModel(models.Model):
    """
    SoftDeletionModel
    """

    deleted_at = models.DateTimeField(blank=True, null=True)

    objects = SoftDeletionManager()
    all_objects = SoftDeletionManager(alive_only=False)

    class Meta:
        """
        Meta
        """

        abstract = True

    def delete(self):
        """
        delete
        """

        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self):
        """
        hard_delete
        """

        super().delete()


class SoftDeletionQuerySet(QuerySet):
    """
    SoftDeletionQuerySet
    """

    def delete(self):
        """
        delete
        :return:
        """

        return super().update(deleted_at=timezone.now())

    def hard_delete(self):
        """
        hard_delete
        :return:
        """

        return super().delete()

    def alive(self):
        """
        alive
        :return:
        """

        return self.filter(deleted_at=None)

    def dead(self):
        """
        It's dead, Jim
        :return:
        """

        return self.exclude(deleted_at=None)


# IFatLinkType Model (StratOp, ADM, HD etc)
class IFatLinkType(SoftDeletionModel):
    """
    IFatLinkType
    """

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=254)
    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
    )
    deleted_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return "{} - {}".format(self.id, self.name)

    class Meta:
        """
        Meta
        """

        verbose_name = "FAT Link Type"
        verbose_name_plural = "FAT Link Types"
        default_permissions = ()


# IFatLink Model
class IFatLink(SoftDeletionModel):
    """
    IFatLink
    """

    ifattime = models.DateTimeField(default=timezone.now)
    fleet = models.CharField(max_length=254, null=True)
    hash = models.CharField(max_length=254)
    creator = models.ForeignKey(User, on_delete=models.SET(get_sentinel_user))
    deleted_at = models.DateTimeField(blank=True, null=True)
    link_type = models.ForeignKey(IFatLinkType, on_delete=models.CASCADE, null=True)
    is_esilink = models.BooleanField(default=False)

    def __str__(self):
        return self.hash[6:]

    class Meta:
        """
        Meta
        """

        verbose_name = "FAT Link"
        verbose_name_plural = "FAT Links"
        permissions = (
            ("manage_imicusfat", "Can manage the imicusfat module"),
            ("stats_corp_own", "Can see own corp stats"),
            ("stats_corp_other", "Can see stats of other corps."),
            (
                "stats_char_other",
                "Can see stats of characters not associated with current user.",
            ),
        )
        ordering = ("-ifattime",)


# ClickIFatDuration Model
class ClickIFatDuration(models.Model):
    """
    ClickIFatDuration
    """

    duration = models.PositiveIntegerField()
    fleet = models.ForeignKey(IFatLink, on_delete=models.CASCADE)


# IFAT Model
class IFat(SoftDeletionModel):
    """
    IFat
    """

    character = models.ForeignKey(EveCharacter, on_delete=models.CASCADE)
    ifatlink = models.ForeignKey(IFatLink, on_delete=models.CASCADE)
    system = models.CharField(max_length=100, null=True)
    shiptype = models.CharField(max_length=100, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return "{} - {}".format(self.ifatlink, self.character)

    class Meta:
        """
        Meta
        """

        verbose_name = "FAT"
        verbose_name_plural = "FATs"
        unique_together = (("character", "ifatlink"),)


# ManualIFat Model
class ManualIFat(models.Model):
    """
    ManualIFat
    """

    creator = models.ForeignKey(User, on_delete=models.SET(get_sentinel_user))
    ifatlink = models.ForeignKey(IFatLink, on_delete=models.CASCADE)
    character = models.ForeignKey(EveCharacter, on_delete=models.CASCADE)

    # Add property for getting the user for a character.

    def __str__(self):
        return "{} - {} ({})".format(self.ifatlink, self.character, self.creator)


# DelLog Model
class DelLog(models.Model):
    """
    DelLog
    """

    # 0 for FatLink, 1 for Fat
    deltype = models.BooleanField(default=0)
    remover = models.ForeignKey(User, on_delete=models.SET(get_sentinel_user))
    string = models.CharField(max_length=100)

    def delt_to_str(self):
        """
        delt_to_str
        :return:
        """

        if self.deltype == 0:
            return "IFatLink"
        else:
            return "IFat"

    def __str__(self):
        return "{}/{} - {}".format(self.delt_to_str(), self.string, self.remover)

    class Meta:
        """
        Meta
        """

        verbose_name = "Delete Log"
        verbose_name_plural = "Delete Logs"
        default_permissions = ()
