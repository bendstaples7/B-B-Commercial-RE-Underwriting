"""ParcelSalesCache model — local mirror of the Cook County Parcel Sales Socrata dataset."""
from app import db


class ParcelSalesCache(db.Model):
    """Local cache of Cook County parcel sale transactions (Socrata dataset wvhk-k5uv)."""
    __tablename__ = 'parcel_sales_cache'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pin = db.Column(db.String(14), nullable=False)
    sale_date = db.Column(db.Date, nullable=True)
    sale_price = db.Column(db.Numeric(precision=14, scale=2), nullable=True)
    # 'class' is a Python reserved word; mapped to DB column 'class'
    class_ = db.Column('class', db.String(10), nullable=True)
    sale_type = db.Column(db.String(50), nullable=True)
    is_multisale = db.Column(db.Boolean, nullable=True)
    sale_filter_less_than_10k = db.Column(db.Boolean, nullable=True)
    sale_filter_deed_type = db.Column(db.Boolean, nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.Index('ix_parcel_sales_pin_sale_date', 'pin', 'sale_date'),
        db.Index('ix_parcel_sales_sale_date', 'sale_date'),
    )

    def __repr__(self):
        return f'<ParcelSalesCache pin={self.pin} sale_date={self.sale_date} sale_price={self.sale_price}>'
