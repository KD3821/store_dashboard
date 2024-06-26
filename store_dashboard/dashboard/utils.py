import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "store_dashboard.settings")

import django

django.setup()

from typing import Dict, List

import openpyxl
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from dotenv import load_dotenv

from .models import items_collection, stores_collection

load_dotenv()

report_time = os.getenv("REPORT_TIME")

channel_layer = get_channel_layer()


@sync_to_async
def get_report_time():
    return report_time


class StoreProcessor:
    def __init__(self, store_id: str) -> None:
        self.store = stores_collection.find_one({"store_id": store_id})

    def get_items(self) -> List[Dict[str, str | int]]:
        items = list()
        for item in items_collection.find({"store_id": self.store.get("store_id")}):
            items.append(
                {"item_id": item.get("item_id"), "quantity": item.get("quantity")}
            )
        return items

    def clean(self) -> None:
        items_collection.delete_many({"store_id": self.store.get("store_id")})
        self.report_ws()

    def supply(self, item_data: dict, trigger_ws=True) -> None:
        quantity = item_data.get("quantity")
        item_id = item_data.get("item_id")

        for item in items_collection.find({"store_id": self.store.get("store_id")}):
            if item.get("item_id") == item_id:
                new_quantity = item.get("quantity") + quantity

                items_collection.find_one_and_update(
                    {"item_id": item_id, "store_id": self.store.get("store_id")},
                    {"$set": {"quantity": new_quantity}},
                )
                break
        else:
            items_collection.insert_one(
                {
                    "store_id": self.store.get("store_id"),
                    "item_id": item_id,
                    "quantity": quantity,
                }
            )

        if trigger_ws:
            self.report_ws()

    def demand(self, item_data: Dict[str, str | int], trigger_ws=True) -> None:
        quantity = item_data.get("quantity")
        item_id = item_data.get("item_id")

        for item in items_collection.find({"store_id": self.store.get("store_id")}):
            if item.get("item_id") == item_id:
                new_quantity = item.get("quantity") - quantity

                if new_quantity > 0:
                    items_collection.find_one_and_update(
                        {"item_id": item_id, "store_id": self.store.get("store_id")},
                        {"$set": {"quantity": new_quantity}},
                    )
                else:
                    items_collection.delete_one(
                        {"store_id": self.store.get("store_id"), "item_id": item_id}
                    )

        if trigger_ws:
            self.report_ws()

    def supply_many(self, item_list: List[Dict[str, str | int]]) -> None:
        for item_data in item_list:
            self.supply(item_data, trigger_ws=False)
        self.report_ws()

    def demand_many(self, item_list: List[Dict[str, str | int]]) -> None:
        for item_data in item_list:
            self.demand(item_data, trigger_ws=False)
        self.report_ws()

    def report_xlsx(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        data = list()

        for item in items_collection.find({"store_id": self.store.get("store_id")}):
            data.append([item.get("item_id"), item.get("quantity")])

        for row in data:
            sheet.append(row)

        filename = f"STORE_{self.store.get('store_id')}.xlsx"
        workbook.save(filename)

        return workbook, filename

    def report_ws(self) -> None:
        store_id = self.store.get("store_id")
        items = self.get_items()
        async_to_sync(channel_layer.group_send)(
            store_id,
            {
                "type": "store_report",
                "report": {"store": {"store_id": store_id, "report": items}},
            },
        )
